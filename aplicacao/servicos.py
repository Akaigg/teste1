"""
Serviços de aplicação: orquestram dados, backtest, seleção e execução.
A interface (menu/CLI) só conversa com este módulo.
"""
from __future__ import annotations

from typing import Callable, List, Optional, Tuple

import pandas as pd

from aplicacao.backtester import Backtester
from aplicacao.executor import Executor
from aplicacao.seletor import SeletorEstrategias
from config.configuracao import Configuracao
from dominio.estrategias.base import EstrategiaBase
from dominio.estrategias.catalogo import construir_catalogo, obter_estrategia
from infraestrutura import persistencia
from infraestrutura.csv_adaptador import ProvedorCSV
from infraestrutura.dados_sinteticos import ProvedorSintetico
from infraestrutura.mt5_adaptador import MT5_DISPONIVEL, AdaptadorMT5, ErroMT5
from infraestrutura.registro import obter_registrador
from infraestrutura.replay import ProvedorReplay
from infraestrutura.simulador_corretora import SimuladorCorretora

_mt5_compartilhado: Optional[AdaptadorMT5] = None


def obter_mt5(cfg: Configuracao):
    """Conexão única com o terminal MT5 (conta já logada)."""
    global _mt5_compartilhado
    if _mt5_compartilhado is None:
        _mt5_compartilhado = AdaptadorMT5(magic=cfg.execucao.magic, desvio=cfg.execucao.desvio_maximo_pontos,
                                          caminho_terminal=cfg.caminho_terminal_mt5, registrador=obter_registrador())
        _mt5_compartilhado.conectar()
    return _mt5_compartilhado


def procurar_simbolos(cfg: Configuracao, filtro: str) -> list:
    """Lista símbolos da corretora (MT5) que contêm o texto do filtro."""
    return obter_mt5(cfg).listar_simbolos(filtro)


def criar_provedor(cfg: Configuracao):
    fonte = cfg.fonte_dados.lower()
    if fonte == "mt5":
        return obter_mt5(cfg)
    if fonte == "csv":
        if not cfg.arquivo_csv:
            raise ValueError("Defina 'arquivo_csv' na configuração para usar a fonte CSV.")
        return ProvedorCSV(cfg.arquivo_csv)
    if fonte == "sintetico":
        return ProvedorSintetico()
    raise ValueError(f"Fonte de dados desconhecida: {cfg.fonte_dados}")


def carregar_dados(cfg: Configuracao) -> pd.DataFrame:
    if not cfg.ativo and cfg.fonte_dados == "mt5":
        raise ValueError("Defina o ativo antes de carregar dados.")
    df = criar_provedor(cfg).obter_candles(cfg.ativo or "SINTETICO", cfg.timeframe, cfg.barras_historico)
    if len(df) < 500:
        raise ValueError(f"Apenas {len(df)} candles disponíveis; são necessários pelo menos 500.")
    return df


def criar_backtester(cfg: Configuracao) -> Backtester:
    return Backtester(cfg.backtest, cfg.valor_ponto, cfg.custo_pontos_por_operacao, cfg.deslizamento_pontos,
                      cfg.contratos, cfg.capital_inicial, horario_inicio=cfg.execucao.horario_inicio,
                      horario_fim=cfg.execucao.horario_fim, perda_maxima_diaria=cfg.execucao.perda_maxima_diaria,
                      distancia_minima_stop=resolver_distancia_minima_stop(cfg),
                      um_trade_por_vez=cfg.execucao.um_trade_por_vez)


def resolver_distancia_minima_stop(cfg: Configuracao) -> float:
    """Distância mínima de stop/alvo: valor configurado ou, se 0 e a fonte for o MT5, o informado pela plataforma."""
    if cfg.execucao.distancia_minima_stop_pontos > 0:
        return float(cfg.execucao.distancia_minima_stop_pontos)
    if cfg.fonte_dados == "mt5" and cfg.ativo:
        try:
            return float(obter_mt5(cfg).distancia_minima_stop(cfg.ativo))
        except Exception:
            return 0.0
    return 0.0


def diagnosticar_ranking(cfg: Configuracao, df: pd.DataFrame, ranking: List[dict], distancia_minima: float) -> dict:
    """Explica por que (e se) as estratégias ficaram inelegíveis."""
    import statistics
    com_erro = [r for r in ranking if r.get("erro")]
    trades_treino = [r.get("metricas_treino", {}).get("total_trades", 0) for r in ranking if not r.get("erro")]
    descartados = [r.get("metricas_treino", {}).get("sinais_descartados_stop_minimo", 0) for r in ranking if not r.get("erro")]
    elegiveis = sum(1 for r in ranking if r["pontuacao_final"] > 0)
    barras_treino = int(len(df) * cfg.backtest.proporcao_treino)
    dias = len(set(df.index.normalize()))
    diag = {
        "estrategias": len(ranking), "elegiveis": elegiveis, "com_erro": len(com_erro),
        "primeiro_erro": com_erro[0]["erro"] if com_erro else "",
        "barras": len(df), "dias": dias, "barras_treino": barras_treino,
        "min_trades_exigido": cfg.backtest.min_trades,
        "mediana_trades_treino": int(statistics.median(trades_treino)) if trades_treino else 0,
        "max_trades_treino": max(trades_treino) if trades_treino else 0,
        "sinais_descartados_stop_minimo_total": int(sum(descartados)),
        "distancia_minima_stop": distancia_minima,
        "horario": f"{cfg.execucao.horario_inicio}-{cfg.execucao.horario_fim}",
        "barras_no_horario": int(criar_backtester(cfg)._mascara_horario(df).sum()),
    }
    causas = []
    if diag["com_erro"] == diag["estrategias"]:
        causas.append(f"todas as estratégias falharam com erro: {diag['primeiro_erro']}")
    if diag["barras_no_horario"] == 0:
        causas.append(f"nenhum candle dentro do horário {diag['horario']} — confira o fuso do servidor MT5 (horário dos candles) e a janela configurada")
    if diag["sinais_descartados_stop_minimo_total"] > 0 and diag["max_trades_treino"] < cfg.backtest.min_trades:
        causas.append(f"distância mínima de stop/alvo ({distancia_minima:.0f} pts) descartou {diag['sinais_descartados_stop_minimo_total']} sinais — "
                      f"se for maior que o esperado para o ativo, defina 'distancia_minima_stop_pontos' manualmente")
    if elegiveis == 0 and diag["max_trades_treino"] < cfg.backtest.min_trades:
        causas.append(f"poucos trades: a estratégia mais ativa fez {diag['max_trades_treino']} trades no treino "
                      f"({barras_treino} candles ≈ {int(dias * cfg.backtest.proporcao_treino)} dias) e o mínimo exigido é "
                      f"{cfg.backtest.min_trades} — aumente 'barras_historico' (e o 'Max bars in chart' do MT5), use um timeframe "
                      f"menor ou reduza 'min_trades'")
    diag["causas"] = causas
    return diag


def gerar_ranking(cfg: Configuracao, df: pd.DataFrame, progresso: Optional[Callable] = None,
                  estrategias: Optional[List[EstrategiaBase]] = None) -> Tuple[List[dict], str]:
    backtester = criar_backtester(cfg)
    seletor = SeletorEstrategias(backtester, cfg.backtest, cfg.ia)
    ranking = seletor.avaliar_todas(df, estrategias or construir_catalogo(), progresso)
    info = {"barras": len(df), "inicio": str(df.index[0]), "fim": str(df.index[-1]),
            "contratos": cfg.contratos, "valor_ponto": cfg.valor_ponto,
            "diagnostico": diagnosticar_ranking(cfg, df, ranking, backtester.distancia_minima_stop)}
    caminho = persistencia.salvar_ranking(ranking, cfg.ativo or "SINTETICO", cfg.timeframe, info)
    return ranking, caminho


def texto_diagnostico(diag: dict) -> str:
    linhas = [f"Diagnóstico: {diag['elegiveis']}/{diag['estrategias']} estratégias elegíveis | {diag['barras']} candles "
              f"({diag['dias']} dias), {diag['barras_treino']} no treino, {diag['barras_no_horario']} dentro do horário "
              f"{diag['horario']} | trades no treino: mediana {diag['mediana_trades_treino']}, máximo {diag['max_trades_treino']} "
              f"(mínimo exigido {diag['min_trades_exigido']}) | distância mínima stop/alvo: {diag['distancia_minima_stop']:.0f} pts "
              f"| sinais descartados por ela: {diag['sinais_descartados_stop_minimo_total']} | estratégias com erro: {diag['com_erro']}"]
    for c in diag.get("causas", []):
        linhas.append(f"  → Causa provável: {c}")
    return "\n".join(linhas)


def carregar_ranking(cfg: Configuracao) -> Optional[dict]:
    return persistencia.carregar_ranking(cfg.ativo or "SINTETICO", cfg.timeframe)


def melhor_estrategia(cfg: Configuracao) -> Optional[EstrategiaBase]:
    """Instancia a estratégia no topo do ranking salvo, já com stop/alvo ajustados."""
    dados = carregar_ranking(cfg)
    if not dados or not dados["ranking"]:
        return None
    topo = dados["ranking"][0]
    if topo["pontuacao_final"] <= 0:
        return None
    estrategia = obter_estrategia(topo["nome"])
    if estrategia is None:
        return None
    estrategia.configurar_risco(topo["mult_stop"], topo["mult_alvo"])
    return estrategia


def instanciar_do_ranking(entrada: dict) -> Optional[EstrategiaBase]:
    e = obter_estrategia(entrada["nome"])
    if e is not None:
        e.configurar_risco(entrada["mult_stop"], entrada["mult_alvo"])
    return e


def backtest_detalhado(cfg: Configuracao, df: pd.DataFrame, estrategia: EstrategiaBase, filtro_ia=None):
    return criar_backtester(cfg).executar(df, estrategia, filtro_ia=filtro_ia)


def preparar_filtro_ia(cfg: Configuracao, df: pd.DataFrame, estrategia: EstrategiaBase):
    if not cfg.ia.ativar:
        return None
    from ia.filtro_ml import FiltroIA
    filtro = FiltroIA(cfg.ia.margem_probabilidade, cfg.ia.min_trades_treino, obter_registrador())
    resultado = backtest_detalhado(cfg, df, estrategia)
    return filtro if filtro.treinar(df, resultado.trades) else None


def montar_executor(cfg: Configuracao, estrategia: EstrategiaBase, df_treino: Optional[pd.DataFrame] = None) -> Executor:
    log = obter_registrador()
    provedor = criar_provedor(cfg)
    replay = cfg.fonte_dados != "mt5"
    if replay:  # sem MT5, o modo simulado faz replay dos dados históricos
        provedor = ProvedorReplay(provedor, cfg.barras_historico, aquecimento=max(500, int(len(df_treino) * cfg.backtest.proporcao_treino)) if df_treino is not None else 500)
        log.info("Fonte de dados não é o MT5: executor rodará em REPLAY dos dados históricos (modo simulado).")
    if cfg.execucao.modo == "real":
        if cfg.fonte_dados != "mt5":
            raise ValueError("Modo REAL exige fonte_dados = 'mt5'.")
        corretora = obter_mt5(cfg)
    else:
        corretora = SimuladorCorretora(cfg.capital_inicial, cfg.valor_ponto, log, cfg.deslizamento_pontos,
                                       cfg.custo_pontos_por_operacao, resolver_distancia_minima_stop(cfg))
    filtro = preparar_filtro_ia(cfg, df_treino, estrategia) if df_treino is not None else None

    def reavaliador():
        try:
            df = carregar_dados(cfg)
            gerar_ranking(cfg, df)
            return melhor_estrategia(cfg)
        except Exception as erro:
            log.error(f"Falha ao reavaliar: {erro}")
            return None

    executor = Executor(cfg, estrategia, provedor, corretora, log, filtro_ia=filtro, reavaliador=reavaliador)
    if replay:
        executor.intervalo = 0
    return executor
