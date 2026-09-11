"""Testes rápidos do motor (rode: python -m pytest testes -q)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aplicacao.backtester import Backtester
from aplicacao.seletor import SeletorEstrategias
from config.configuracao import Configuracao
from dominio.estrategias.catalogo import construir_catalogo
from infraestrutura.dados_sinteticos import ProvedorSintetico


def _cfg():
    cfg = Configuracao()
    cfg.backtest.grade_stop_atr = [1.5]
    cfg.backtest.grade_alvo_atr = [2.0]
    cfg.backtest.min_trades = 5
    return cfg


def test_catalogo_tem_estrategias_de_todas_as_familias():
    catalogo = construir_catalogo()
    assert len(catalogo) >= 40
    assert {e.familia for e in catalogo} == {"pontuacao_ponderada", "regime_adaptativo", "estatistica", "confluencia",
                                            "divergencia", "fluxo_volume", "estrutura_mercado", "ensemble"}


def test_vies_fica_no_intervalo_e_ensemble_usa_membros():
    df = ProvedorSintetico().obter_candles("X", "M5", 3000)
    for e in construir_catalogo():
        v = e.vies(df)
        if v is None:
            continue
        assert len(v) == len(df)
        assert v.dropna().between(-1.0, 1.0).all(), e.nome
    ensemble = next(e for e in construir_catalogo() if e.familia == "ensemble")
    assert len(ensemble.membros) >= 5


def test_walk_forward_produz_janelas_fora_da_amostra():
    from aplicacao.walkforward import AnalisadorWalkForward, planejar_janelas
    cfg = _cfg()
    cfg.backtest.grade_stop_atr, cfg.backtest.grade_alvo_atr = [1.0, 2.0], [2.0, 3.0]
    df = ProvedorSintetico().obter_candles("X", "M5", 5000)
    janelas = planejar_janelas(len(df), 4, 0.7, ancorado=False)
    assert len(janelas) == 4
    for (a, b, c, d), (a2, b2, c2, d2) in zip(janelas, janelas[1:]):
        assert a < b == c < d == c2  # treino antes do teste; testes consecutivos sem sobreposição
    assert janelas[-1][3] == len(df)
    bt = Backtester(cfg.backtest, 1.0, 0.0, 0.0, 1, 10000)
    estrategia = next(e for e in construir_catalogo() if e.identificador == "fluxo_ponderado")
    r = AnalisadorWalkForward(bt, cfg.backtest, 10000).analisar(df, estrategia, 4, 0.7, False, mult_fixos=(1.5, 3.0))
    assert len(r["janelas"]) == 4 and r["veredito"] in {"robusta", "moderada", "fragil", "inconclusiva"}
    assert 0 <= r["pontuacao"] <= 100 and "metricas_teste_fixo" in r
    assert len(r["curva_teste"]) == r["metricas_teste"]["total_trades"] + 1
    for j in r["janelas"]:
        assert (j["mult_stop"], j["mult_alvo"]) in {(1.0, 2.0), (1.0, 3.0), (2.0, 2.0), (2.0, 3.0)}


def test_todas_estrategias_geram_sinais_validos():
    df = ProvedorSintetico().obter_candles("X", "M5", 3000)
    for e in construir_catalogo():
        s = e.sinais_limpos(df)
        assert len(s) == len(df)
        assert set(s.unique()) <= {-1, 0, 1}, e.nome


def test_backtest_nao_olha_futuro_e_fecha_no_dia():
    cfg = _cfg()
    df = ProvedorSintetico().obter_candles("X", "M5", 3000)
    bt = Backtester(cfg.backtest, 1.0, 0.0, 0.0, 1, 10000)
    res = bt.executar(df, construir_catalogo()[0])
    for t in res.trades:
        assert t.indice_saida >= t.indice_entrada
        assert t.data_entrada.normalize() == t.data_saida.normalize()


def test_seletor_produz_ranking_ordenado():
    cfg = _cfg()
    df = ProvedorSintetico().obter_candles("X", "M5", 3000)
    bt = Backtester(cfg.backtest, 1.0, 0.0, 0.0, 1, 10000)
    ranking = SeletorEstrategias(bt, cfg.backtest).avaliar_todas(df, construir_catalogo()[:5])
    notas = [r["pontuacao_final"] for r in ranking]
    assert notas == sorted(notas, reverse=True)


def test_backtest_respeita_janela_de_horario():
    cfg = _cfg()
    df = ProvedorSintetico().obter_candles("X", "M5", 3000)
    bt = Backtester(cfg.backtest, 1.0, 0.0, 0.0, 1, 10000, horario_inicio="10:00", horario_fim="16:00")
    for e in construir_catalogo()[:10]:
        for t in bt.executar(df, e).trades:
            assert "10:00" <= t.data_entrada.strftime("%H:%M") <= "16:00"
            assert t.data_saida.strftime("%H:%M") <= "16:00"
