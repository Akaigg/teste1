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


def test_catalogo_tem_mais_de_100_estrategias():
    assert len(construir_catalogo()) >= 100


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
