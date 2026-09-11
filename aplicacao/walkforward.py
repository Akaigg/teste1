"""
Análise WALK-FORWARD: mede se a consistência de uma estratégia se mantém
quando stop/alvo são reotimizados periodicamente e testados sempre em dados
que a otimização nunca viu.

Os dados são divididos em N janelas de TESTE consecutivas. Para cada janela:
  1. TREINO = trecho imediatamente anterior (janela deslizante, tamanho fixo)
     ou tudo desde o início dos dados (ancorado);
  2. no treino, a grade de stop/alvo é avaliada com a mesma pontuação de
     consistência do ranking e a melhor combinação é escolhida;
  3. a combinação é aplicada no TESTE (fora da amostra) e, para comparação,
     também os multiplicadores fixos escolhidos pelo ranking (se informados).

Os trades de todos os testes são concatenados numa única curva fora da
amostra, que é a melhor estimativa de como a estratégia teria se comportado
sendo reajustada ao longo do tempo. Métricas de robustez:
  - % de janelas de teste lucrativas;
  - eficiência walk-forward (WFE): lucro por barra no teste / lucro por barra
    no treino (1.0 = o teste rendeu tanto quanto o treino; < 0.5 sugere
    sobreajuste);
  - estabilidade dos parâmetros: fração das janelas que escolheram a
    combinação de stop/alvo mais frequente;
  - pontuação walk-forward (0-100) e veredito (robusta / moderada / frágil).
"""
from __future__ import annotations

import itertools
from collections import Counter
from typing import Callable, List, Optional, Tuple

import numpy as np
import pandas as pd

from aplicacao.backtester import Backtester
from aplicacao.metricas import calcular_metricas
from aplicacao.seletor import pontuar_consistencia
from config.configuracao import ConfiguracaoBacktest
from dominio.estrategias.base import EstrategiaBase
from dominio.modelos import Trade


def planejar_janelas(n_barras: int, n_janelas: int, proporcao_treino: float, ancorado: bool) -> List[Tuple[int, int, int, int]]:
    """Lista de (inicio_treino, fim_treino, inicio_teste, fim_teste) em índices de barra (fim exclusivo)."""
    if n_janelas < 2:
        raise ValueError("O walk-forward precisa de pelo menos 2 janelas.")
    if not 0.3 <= proporcao_treino <= 0.95:
        raise ValueError("A proporção de treino deve ficar entre 0.3 e 0.95.")
    razao = proporcao_treino / (1.0 - proporcao_treino)      # tamanho do treino em unidades de teste
    barras_teste = int(n_barras / (n_janelas + razao))
    barras_treino = int(razao * barras_teste)
    if barras_teste < 100 or barras_treino < 300:
        raise ValueError(f"Dados insuficientes para {n_janelas} janelas: cada teste teria {barras_teste} barras e cada treino "
                         f"{barras_treino}. Reduza o número de janelas ou aumente o histórico.")
    janelas = []
    for k in range(n_janelas):
        inicio_teste = barras_treino + k * barras_teste
        fim_teste = n_barras if k == n_janelas - 1 else inicio_teste + barras_teste
        inicio_treino = 0 if ancorado else inicio_teste - barras_treino
        janelas.append((inicio_treino, inicio_teste, inicio_teste, fim_teste))
    return janelas


def _resumo_janela(res) -> dict:
    m = res.metricas
    return {"trades": m.get("total_trades", 0), "lucro": m.get("lucro_liquido", 0.0), "fator_lucro": m.get("fator_lucro", 0.0),
            "drawdown": m.get("drawdown_maximo", 0.0), "acerto": m.get("taxa_acerto", 0.0), "expectativa": m.get("expectativa", 0.0)}


class AnalisadorWalkForward:
    def __init__(self, backtester: Backtester, cfg: ConfiguracaoBacktest, capital_inicial: float):
        self.backtester = backtester
        self.cfg = cfg
        self.capital_inicial = capital_inicial

    # ------------------------------------------------------------------ núcleo
    def analisar(self, df: pd.DataFrame, estrategia: EstrategiaBase, n_janelas: int, proporcao_treino: float,
                 ancorado: bool = False, mult_fixos: Optional[Tuple[float, float]] = None,
                 progresso: Optional[Callable[[int, int, str], None]] = None) -> dict:
        cfg = self.cfg
        n = len(df)
        janelas = planejar_janelas(n, n_janelas, proporcao_treino, ancorado)
        sinais, valores_atr = self.backtester.preparar(df, estrategia)
        grade = list(itertools.product(cfg.grade_stop_atr, cfg.grade_alvo_atr))
        # o mínimo de trades do ranking vale para `proporcao_treino` dos dados; aqui é escalado pelo tamanho do trecho
        trades_por_barra = cfg.min_trades / max(1.0, n * cfg.proporcao_treino)

        resultados = []
        trades_teste: List[Trade] = []
        trades_fixo: List[Trade] = []
        cortes_curva = []
        lucro_treino_total = barras_treino_total = 0.0
        for k, (a, b, c, d) in enumerate(janelas, 1):
            if progresso:
                progresso(k, len(janelas), f"{estrategia.nome}: janela {k}/{len(janelas)}")
            df_treino, df_teste = df.iloc[a:b], df.iloc[c:d]
            min_treino = max(5, int(trades_por_barra * (b - a)))
            min_teste = max(3, int(trades_por_barra * (d - c)))

            melhor = None
            for ms, ma in grade:
                res = self.backtester.simular(df_treino, estrategia, sinais[a:b], valores_atr[a:b], ms, ma)
                nota = pontuar_consistencia(res, cfg.n_janelas, min_treino)
                if melhor is None or nota["pontuacao"] > melhor[0]["pontuacao"]:
                    melhor = (nota, res, ms, ma)
            nota_treino, res_treino, ms, ma = melhor

            res_teste = self.backtester.simular(df_teste, estrategia, sinais[c:d], valores_atr[c:d], ms, ma)
            nota_teste = pontuar_consistencia(res_teste, max(2, cfg.n_janelas // 2), min_teste)
            cortes_curva.append(len(trades_teste))
            trades_teste.extend(self._deslocar(res_teste.trades, c))

            lucro_treino = res_treino.metricas.get("lucro_liquido", 0.0)
            lucro_teste = res_teste.metricas.get("lucro_liquido", 0.0)
            lucro_treino_total += lucro_treino
            barras_treino_total += (b - a)
            ritmo_treino = lucro_treino / (b - a)
            eficiencia = (lucro_teste / (d - c)) / ritmo_treino if ritmo_treino > 0 else None

            janela = {
                "numero": k, "inicio_treino": str(df.index[a]), "fim_treino": str(df.index[b - 1]),
                "inicio_teste": str(df.index[c]), "fim_teste": str(df.index[d - 1]),
                "barras_treino": b - a, "barras_teste": d - c, "mult_stop": ms, "mult_alvo": ma,
                "nota_treino": nota_treino["pontuacao"], "nota_teste": nota_teste["pontuacao"],
                "treino": _resumo_janela(res_treino),
                "teste": _resumo_janela(res_teste),
                "eficiencia": None if eficiencia is None else round(float(eficiencia), 3),
            }
            if mult_fixos is not None:
                res_fixo = self.backtester.simular(df_teste, estrategia, sinais[c:d], valores_atr[c:d], *mult_fixos)
                trades_fixo.extend(self._deslocar(res_fixo.trades, c))
                janela["teste_fixo"] = _resumo_janela(res_fixo)
            resultados.append(janela)

        return self._consolidar(estrategia, df, janelas, resultados, trades_teste, trades_fixo, cortes_curva,
                                lucro_treino_total, barras_treino_total, n_janelas, proporcao_treino, ancorado, mult_fixos)

    @staticmethod
    def _deslocar(trades: List[Trade], deslocamento: int) -> List[Trade]:
        """Índices dos trades do trecho passam a ser relativos ao DataFrame completo."""
        for t in trades:
            t.indice_entrada += deslocamento
            t.indice_saida += deslocamento
        return trades

    # ------------------------------------------------------------- consolidação
    def _consolidar(self, estrategia, df, janelas, resultados, trades_teste, trades_fixo, cortes_curva,
                    lucro_treino_total, barras_treino_total, n_janelas, proporcao_treino, ancorado, mult_fixos) -> dict:
        metricas = calcular_metricas(trades_teste, self.capital_inicial)
        lucros = [j["teste"]["lucro"] for j in resultados]
        pct_positivas = float(np.mean([l > 0 for l in lucros])) if lucros else 0.0
        pct_notas = float(np.mean([j["nota_teste"] > 0 for j in resultados])) if resultados else 0.0

        barras_teste_total = sum(j["barras_teste"] for j in resultados)
        ritmo_treino = lucro_treino_total / barras_treino_total if barras_treino_total else 0.0
        ritmo_teste = metricas["lucro_liquido"] / barras_teste_total if barras_teste_total else 0.0
        eficiencia = float(ritmo_teste / ritmo_treino) if ritmo_treino > 0 else (0.0 if ritmo_teste <= 0 else 1.0)

        combinacoes = Counter((j["mult_stop"], j["mult_alvo"]) for j in resultados)
        (ms_freq, ma_freq), vezes = combinacoes.most_common(1)[0]
        estabilidade = vezes / len(resultados)

        pontuacao, veredito, motivos = self._pontuar(metricas, pct_positivas, eficiencia, estabilidade, len(resultados))
        curva = [self.capital_inicial]
        for t in trades_teste:
            curva.append(curva[-1] + t.resultado_financeiro)

        saida = {
            "estrategia": estrategia.nome, "familia": estrategia.familia, "descricao": estrategia.descricao,
            "parametros": dict(estrategia.parametros), "n_janelas": n_janelas, "proporcao_treino": proporcao_treino,
            "ancorado": ancorado, "barras": len(df), "barras_treino": janelas[0][1] - janelas[0][0],
            "barras_teste": janelas[0][3] - janelas[0][2], "inicio": str(df.index[0]), "fim": str(df.index[-1]),
            "janelas": resultados, "metricas_teste": metricas,
            "pct_janelas_positivas": round(pct_positivas * 100, 1), "pct_janelas_nota_positiva": round(pct_notas * 100, 1),
            "eficiencia": round(eficiencia, 3), "estabilidade_parametros": round(estabilidade, 3),
            "parametros_mais_frequentes": [ms_freq, ma_freq], "pontuacao": pontuacao, "veredito": veredito, "motivos": motivos,
            "curva_teste": curva, "cortes_curva": cortes_curva, "mult_fixos": list(mult_fixos) if mult_fixos else None,
        }
        if mult_fixos is not None:
            saida["metricas_teste_fixo"] = calcular_metricas(trades_fixo, self.capital_inicial)
            curva_fixo = [self.capital_inicial]
            for t in trades_fixo:
                curva_fixo.append(curva_fixo[-1] + t.resultado_financeiro)
            saida["curva_teste_fixo"] = curva_fixo
        return saida

    @staticmethod
    def _pontuar(m: dict, pct_positivas: float, eficiencia: float, estabilidade: float, n_janelas: int):
        motivos = []
        poucos_trades = m["total_trades"] < 3 * n_janelas
        if poucos_trades:
            motivos.append(f"poucos trades fora da amostra ({m['total_trades']})")
        fl_norm = float(np.clip((m["fator_lucro"] - 1.0), 0.0, 1.0))
        lucro_bruto = m.get("lucro_bruto", 0.0)
        dd_norm = 1.0 - float(np.clip(m["drawdown_maximo"] / lucro_bruto if lucro_bruto > 0 else 1.0, 0.0, 1.0))
        ef_norm = float(np.clip(eficiencia, 0.0, 1.0))
        pontuacao = 100 * (0.35 * pct_positivas + 0.25 * ef_norm + 0.20 * fl_norm + 0.10 * dd_norm + 0.10 * estabilidade)
        if m["lucro_liquido"] <= 0:
            pontuacao *= 0.5
            motivos.append("prejuízo líquido fora da amostra")
        if eficiencia < 0.5:
            motivos.append(f"eficiência walk-forward baixa ({eficiencia:.2f}): o teste rende muito menos que o treino (sobreajuste)")
        if pct_positivas < 0.5:
            motivos.append(f"só {pct_positivas:.0%} das janelas de teste foram lucrativas")
        if estabilidade < 0.4:
            motivos.append(f"stop/alvo escolhidos mudam muito entre janelas (estabilidade {estabilidade:.0%})")
        if poucos_trades:
            veredito = "inconclusiva"
        elif pontuacao >= 60 and pct_positivas >= 0.6 and m["lucro_liquido"] > 0 and eficiencia >= 0.5:
            veredito = "robusta"
        elif pontuacao >= 40 and m["lucro_liquido"] > 0:
            veredito = "moderada"
        else:
            veredito = "fragil"
        return round(float(pontuacao), 2), veredito, motivos
