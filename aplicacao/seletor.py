"""
Seleção automática da estratégia mais CONSISTENTE.

Processo para cada estratégia:
  1. Divide os dados em TREINO (proporcao_treino) e VALIDAÇÃO (restante).
  2. No treino, testa a grade de multiplicadores de stop/alvo e escolhe a
     combinação com maior pontuação de consistência.
  3. Aplica a combinação escolhida na validação (fora da amostra).
  4. Nota final = média ponderada (treino, validação), com peso maior na
     validação para reduzir o sobreajuste.
  5. Com o filtro de IA ativo: o filtro é treinado APENAS nos trades do
     treino e aplicado na validação; a estratégia recebe uma segunda nota
     ("com IA") e o ranking é ordenado pela nota da opção ativa. Assim dá
     para ver, estratégia por estratégia, se a IA ajuda ou atrapalha fora
     da amostra.

Pontuação de consistência (0 a 100) - privilegia regularidade, não pico de lucro:
  - % de janelas temporais lucrativas ................ 30%
  - estabilidade (média/desvio dos resultados por janela) 25%
  - fator de lucro (limitado a 3) .................... 20%
  - drawdown relativo ao lucro bruto ................. 15%
  - linearidade da curva de capital (R²) ............. 10%
  - estratégias com prejuízo líquido têm a nota reduzida à metade;
  - estratégias com poucos trades recebem nota zero.
"""
from __future__ import annotations

import itertools
from typing import Callable, List, Optional

import numpy as np
import pandas as pd

from aplicacao.backtester import Backtester
from config.configuracao import ConfiguracaoBacktest
from dominio.estrategias.base import EstrategiaBase
from dominio.modelos import ResultadoBacktest


def pontuar_consistencia(resultado: ResultadoBacktest, n_janelas: int, min_trades: int) -> dict:
    trades = resultado.trades
    m = resultado.metricas
    if len(trades) < max(min_trades, 2):
        return {"pontuacao": 0.0, "janelas_positivas_pct": 0.0, "estabilidade": 0.0, "r2": 0.0, "motivo": "poucos_trades"}

    tamanho = max(1.0, resultado.n_barras / n_janelas)
    por_janela = np.zeros(n_janelas)
    for t in trades:
        k = min(int(t.indice_entrada // tamanho), n_janelas - 1)
        por_janela[k] += t.resultado_financeiro

    pct_positivas = float((por_janela > 0).mean())
    media, desvio = por_janela.mean(), por_janela.std() + 1e-9
    estabilidade = float(np.clip(media / desvio, -1.0, 2.0))
    estabilidade_norm = (estabilidade + 1.0) / 3.0

    fator_lucro_norm = float(np.clip(m["fator_lucro"], 0.0, 3.0) / 3.0)
    lucro_bruto = m.get("lucro_bruto", 0.0)
    dd_rel = m["drawdown_maximo"] / lucro_bruto if lucro_bruto > 0 else 1.0
    dd_norm = 1.0 - float(np.clip(dd_rel, 0.0, 1.0))

    curva = np.cumsum([t.resultado_financeiro for t in trades])
    x = np.arange(len(curva))
    if len(curva) > 2 and curva.std() > 0:
        r2 = float(np.corrcoef(x, curva)[0, 1] ** 2)
        if curva[-1] < 0:
            r2 = 0.0
    else:
        r2 = 0.0

    pontuacao = 100 * (0.30 * pct_positivas + 0.25 * estabilidade_norm + 0.20 * fator_lucro_norm
                       + 0.15 * dd_norm + 0.10 * r2)
    if m["lucro_liquido"] <= 0:
        pontuacao *= 0.5
    return {"pontuacao": round(float(pontuacao), 2), "janelas_positivas_pct": round(pct_positivas * 100, 1),
            "estabilidade": round(estabilidade, 3), "r2": round(r2, 3), "motivo": "ok"}


class SeletorEstrategias:
    def __init__(self, backtester: Backtester, cfg: ConfiguracaoBacktest, cfg_ia=None):
        self.backtester = backtester
        self.cfg = cfg
        self.cfg_ia = cfg_ia
        self.usar_ia = bool(cfg_ia is not None and getattr(cfg_ia, "ativar", False))
        self._caracteristicas = None

    def _preparar_ia(self, df: pd.DataFrame) -> None:
        if not self.usar_ia:
            return
        from ia.filtro_ml import SKLEARN_DISPONIVEL, extrair_caracteristicas
        if not SKLEARN_DISPONIVEL:
            self.usar_ia = False
            return
        self._caracteristicas = extrair_caracteristicas(df)

    def _avaliar_com_ia(self, df_valid, estrategia, sinais, valores_atr, corte, res_treino, ms, ma, min_trades_valid):
        """Treina o filtro nos trades do treino e mede a validação com os sinais vetados."""
        from ia.filtro_ml import FiltroIA
        filtro = FiltroIA(self.cfg_ia.margem_probabilidade, self.cfg_ia.min_trades_treino, n_arvores=100)
        treinou = filtro.treinar(None, res_treino.trades, calcular_acuracia=False, caracteristicas=self._caracteristicas)
        if not treinou:
            return None
        entradas = filtro.filtrar_sinais(self._caracteristicas, sinais)
        vetados = int(((sinais[corte:] != 0) & (entradas[corte:] == 0)).sum())
        res = self.backtester.simular(df_valid, estrategia, sinais[corte:], valores_atr[corte:], ms, ma,
                                      sinais_entrada=entradas[corte:])
        nota = pontuar_consistencia(res, max(2, self.cfg.n_janelas // 2), min_trades_valid)
        return {"nota": nota, "resultado": res, "vetados": vetados, "sinais_validacao": int((sinais[corte:] != 0).sum())}

    def avaliar(self, df: pd.DataFrame, estrategia: EstrategiaBase) -> dict:
        cfg = self.cfg
        if self.usar_ia and self._caracteristicas is None:
            self._preparar_ia(df)
        sinais, valores_atr = self.backtester.preparar(df, estrategia)
        n = len(df)
        corte = int(n * cfg.proporcao_treino)
        df_treino, df_valid = df.iloc[:corte], df.iloc[corte:]
        min_trades_valid = max(5, int(cfg.min_trades * (1 - cfg.proporcao_treino)))

        melhor = None
        for ms, ma in itertools.product(cfg.grade_stop_atr, cfg.grade_alvo_atr):
            res = self.backtester.simular(df_treino, estrategia, sinais[:corte], valores_atr[:corte], ms, ma)
            nota = pontuar_consistencia(res, cfg.n_janelas, cfg.min_trades)
            if melhor is None or nota["pontuacao"] > melhor[0]["pontuacao"]:
                melhor = (nota, res, ms, ma)
        nota_treino, res_treino, ms, ma = melhor

        res_valid = self.backtester.simular(df_valid, estrategia, sinais[corte:], valores_atr[corte:], ms, ma)
        nota_valid = pontuar_consistencia(res_valid, max(2, cfg.n_janelas // 2), min_trades_valid)
        res_total = self.backtester.simular(df, estrategia, sinais, valores_atr, ms, ma)

        pv = cfg.peso_validacao
        final_sem_ia = (1 - pv) * nota_treino["pontuacao"] + pv * nota_valid["pontuacao"]
        if nota_treino["pontuacao"] == 0:
            final_sem_ia = 0.0  # inelegível no treino
        estrategia.configurar_risco(ms, ma)
        entrada = {
            "nome": estrategia.nome, "familia": estrategia.familia, "descricao": estrategia.descricao,
            "parametros": dict(estrategia.parametros), "mult_stop": ms, "mult_alvo": ma,
            "pontuacao_final": round(float(final_sem_ia), 2), "pontuacao_final_sem_ia": round(float(final_sem_ia), 2),
            "pontuacao_treino": nota_treino["pontuacao"], "pontuacao_validacao": nota_valid["pontuacao"],
            "consistencia_treino": nota_treino, "consistencia_validacao": nota_valid,
            "metricas_treino": res_treino.metricas, "metricas_validacao": res_valid.metricas,
            "metricas_total": res_total.metricas, "ia_no_ranking": self.usar_ia, "ia_treinada": False,
        }
        if self.usar_ia and nota_treino["pontuacao"] > 0:
            com_ia = self._avaliar_com_ia(df_valid, estrategia, sinais, valores_atr, corte, res_treino, ms, ma, min_trades_valid)
            if com_ia is not None:
                final_com_ia = (1 - pv) * nota_treino["pontuacao"] + pv * com_ia["nota"]["pontuacao"]
                entrada.update({
                    "ia_treinada": True,
                    "pontuacao_final_com_ia": round(float(final_com_ia), 2),
                    "pontuacao_validacao_com_ia": com_ia["nota"]["pontuacao"],
                    "consistencia_validacao_com_ia": com_ia["nota"],
                    "metricas_validacao_com_ia": com_ia["resultado"].metricas,
                    "ia_vetos_validacao": com_ia["vetados"], "ia_sinais_validacao": com_ia["sinais_validacao"],
                })
                entrada["pontuacao_final"] = entrada["pontuacao_final_com_ia"]  # nota da opção ativa
        return entrada

    def avaliar_todas(self, df: pd.DataFrame, estrategias: List[EstrategiaBase],
                      progresso: Optional[Callable[[int, int, str], None]] = None) -> List[dict]:
        ranking = []
        total = len(estrategias)
        for k, estrategia in enumerate(estrategias, 1):
            if progresso:
                progresso(k, total, estrategia.nome)
            try:
                ranking.append(self.avaliar(df, estrategia))
            except Exception as erro:  # uma estratégia com erro não derruba o ranking
                ranking.append({"nome": estrategia.nome, "familia": estrategia.familia, "descricao": estrategia.descricao,
                                "parametros": dict(estrategia.parametros), "mult_stop": estrategia.mult_stop,
                                "mult_alvo": estrategia.mult_alvo, "pontuacao_final": 0.0, "pontuacao_treino": 0.0,
                                "pontuacao_validacao": 0.0, "erro": str(erro),
                                "metricas_treino": {}, "metricas_validacao": {}, "metricas_total": {}})
        ranking.sort(key=lambda r: (r["pontuacao_final"], r.get("metricas_total", {}).get("lucro_liquido", 0)), reverse=True)
        for pos, r in enumerate(ranking, 1):
            r["posicao"] = pos
        return ranking
