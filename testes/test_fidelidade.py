"""
Teste de fidelidade: o executor (em replay, com corretora simulada) deve
produzir exatamente os mesmos trades que o backtest no mesmo trecho de dados.
Se este teste quebrar, existe risco de "trade fantasma".
"""
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from aplicacao import servicos
from config.configuracao import Configuracao
from dominio.estrategias.catalogo import obter_estrategia
from infraestrutura.registro import obter_registrador

CASOS = [("score_tendencia_9_21_55_0p35", 1.5, 3.0, 0.0, 0.0, 600.0, True, 0.0),
         ("score_tendencia_9_21_55_0p35", 1.5, 3.0, 1.0, 5.0, 0.0, True, 0.0, False),
         ("regime_adaptativo_20_9_50", 2.0, 4.0, 0.0, 3.0, 400.0, True, 0.0, False),
         ("score_tendencia_9_21_55_0p35", 1.5, 3.0, 0.0, 0.0, 600.0, False, 0.0),
         ("score_reversao_20_0p45_30", 1.0, 1.5, 2.0, 1.0, 0.0, True, 150.0),
         ("score_reversao_20_0p45_30", 1.0, 1.5, 2.0, 1.0, 0.0, False, 150.0),
         ("forca_candle_0p8_0p5", 2.0, 3.0, 0.0, 0.0, 0.0, True, 0.0),
         ("forca_candle_0p8_0p5", 2.0, 3.0, 0.0, 0.0, 0.0, False, 200.0),
         ("bandas_vwap_reversao_2p0_6", 1.5, 2.0, 1.0, 0.0, 0.0, True, 250.0),
         ("confluencia_tf_3_12", 1.5, 3.0, 0.0, 0.0, 0.0, True, 0.0),
         ("ensemble_0p3_4_3", 2.0, 3.0, 1.0, 2.0, 0.0, True, 0.0)]


@pytest.mark.parametrize("caso", CASOS)
def test_executor_reproduz_backtest(caso):
    nome, ms, ma, custo, desl, limite, um_por_vez, dist_min = caso[:8]
    fechar_fim_dia = caso[8] if len(caso) > 8 else True
    obter_registrador().setLevel(logging.ERROR)
    estrategia = obter_estrategia(nome)
    estrategia.configurar_risco(ms, ma)
    janela_executor = max(estrategia.barras_minimas() * 2, 1000) + 1  # candles que o executor pede a cada ciclo
    cfg = Configuracao()
    cfg.fonte_dados, cfg.ativo, cfg.barras_historico = "sintetico", "TESTE", max(3000, janela_executor + 2500)
    cfg.execucao.horario_inicio, cfg.execucao.horario_fim = "09:30", "16:30"
    cfg.execucao.perda_maxima_diaria = limite
    cfg.custo_pontos_por_operacao, cfg.deslizamento_pontos = custo, desl
    cfg.execucao.um_trade_por_vez = um_por_vez
    cfg.execucao.distancia_minima_stop_pontos = dist_min
    cfg.backtest.fechar_fim_dia = fechar_fim_dia
    df = servicos.carregar_dados(cfg)
    resultado = servicos.backtest_detalhado(cfg, df, estrategia)
    # inicia o replay num ponto em que o backtest está zerado (logo após uma saída), para os dois partirem do mesmo estado
    saida = min(t.indice_saida for t in resultado.trades if t.indice_saida >= max(1000, janela_executor))
    aquecimento = saida + (2 if um_por_vez else 1)
    backtest = [(t.data_entrada, t.direcao, round(t.preco_entrada, 2), round(t.resultado_financeiro, 2))
                for t in resultado.trades if t.indice_entrada >= aquecimento]
    if dist_min:
        assert resultado.sinais_descartados_stop_minimo > 0  # o caso precisa exercitar o descarte
    executor = servicos.montar_executor(cfg, estrategia, None)
    executor.provedor.aquecimento = aquecimento
    executor.iniciar()
    vivo = [(h["entrada_em"], h["direcao"], round(h["entrada"], 2), round(h["resultado"], 2))
            for h in executor.corretora.historico]
    # o replay termina antes do último candle: um trade final aberto no backtest pode não existir no executor
    # (dois, se `um_trade_por_vez` estiver desligado e o backtest reverter no penúltimo candle)
    assert vivo == backtest[:len(vivo)]
    assert len(backtest) - len(vivo) <= (1 if um_por_vez else 2)


def test_um_trade_por_vez_nunca_sobrepoe_e_espera_o_candle_seguinte():
    cfg = Configuracao()
    cfg.fonte_dados, cfg.ativo, cfg.barras_historico = "sintetico", "TESTE", 3000
    cfg.execucao.um_trade_por_vez = True
    df = servicos.carregar_dados(cfg)
    e = obter_estrategia("score_reversao_20_0p45_30")
    e.configurar_risco(1.0, 1.5)
    trades = servicos.backtest_detalhado(cfg, df, e).trades
    for anterior, atual in zip(trades, trades[1:]):
        assert atual.indice_entrada > anterior.indice_saida + 1  # sem sobreposição e sem entrada no candle seguinte à saída


def test_executor_reproduz_backtest_com_filtro_ia():
    """Com o mesmo modelo de IA nos dois lados, executor e backtest vetam os mesmos sinais."""
    from ia.filtro_ml import SKLEARN_DISPONIVEL, FiltroIA
    if not SKLEARN_DISPONIVEL:
        pytest.skip("scikit-learn ausente")
    obter_registrador().setLevel(logging.ERROR)
    cfg = Configuracao()
    cfg.fonte_dados, cfg.ativo, cfg.barras_historico = "sintetico", "TESTE", 3000
    cfg.execucao.horario_inicio, cfg.execucao.horario_fim = "09:30", "16:30"
    cfg.ia.ativar, cfg.ia.min_trades_treino = True, 40
    df = servicos.carregar_dados(cfg)
    e = obter_estrategia("score_tendencia_9_21_55_0p35")
    e.configurar_risco(1.5, 3.0)
    sem_ia = servicos.backtest_detalhado(cfg, df, e)
    filtro = FiltroIA(cfg.ia.margem_probabilidade, cfg.ia.min_trades_treino)
    assert filtro.treinar(df, sem_ia.trades, calcular_acuracia=False)
    com_ia = servicos.backtest_detalhado(cfg, df, e, filtro_ia=filtro)
    assert 0 < len(com_ia.trades) < len(sem_ia.trades)  # a IA vetou algo, mas não tudo
    saida = min(t.indice_saida for t in com_ia.trades if t.indice_saida >= 1000)
    aquecimento = saida + 2
    backtest = [(t.data_entrada, t.direcao, round(t.preco_entrada, 2), round(t.resultado_financeiro, 2))
                for t in com_ia.trades if t.indice_entrada >= aquecimento]
    executor = servicos.montar_executor(cfg, e, df)  # treina o mesmo modelo (mesma semente, mesmos trades)
    executor.provedor.aquecimento = aquecimento
    executor.iniciar()
    vivo = [(h["entrada_em"], h["direcao"], round(h["entrada"], 2), round(h["resultado"], 2)) for h in executor.corretora.historico]
    assert vivo == backtest[:len(vivo)]
    assert len(backtest) - len(vivo) <= 1


def test_ranking_com_ia_traz_as_duas_notas():
    from ia.filtro_ml import SKLEARN_DISPONIVEL
    if not SKLEARN_DISPONIVEL:
        pytest.skip("scikit-learn ausente")
    from dominio.estrategias.catalogo import construir_catalogo
    cfg = Configuracao()
    cfg.fonte_dados, cfg.ativo, cfg.barras_historico = "sintetico", "TESTE", 3000
    cfg.ia.ativar, cfg.ia.min_trades_treino = True, 30
    cfg.backtest.grade_stop_atr, cfg.backtest.grade_alvo_atr = [1.5], [3.0]
    df = servicos.carregar_dados(cfg)
    ranking, _ = servicos.gerar_ranking(cfg, df, estrategias=construir_catalogo()[:8])
    treinadas = [r for r in ranking if r.get("ia_treinada")]
    assert treinadas, "nenhuma estratégia teve o filtro treinado"
    for r in treinadas:
        assert "pontuacao_final_com_ia" in r and "pontuacao_final_sem_ia" in r
        assert r["pontuacao_final"] == r["pontuacao_final_com_ia"]  # ordenado pela opção ativa
        assert r["ia_vetos_validacao"] <= r["ia_sinais_validacao"]
