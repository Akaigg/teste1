"""Regressão: a conversão das rates do MT5 não pode gerar NaN (bug de alinhamento de índice)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from dominio import indicadores as ind
from dominio.estrategias.catalogo import construir_catalogo
from infraestrutura.mt5_adaptador import AdaptadorMT5


def _rates_falsas(n=600):
    rng = np.random.default_rng(3)
    fech = 100000 + np.cumsum(rng.normal(0, 50, n))
    linhas = [(1725000000 + 300 * i, fech[i] - 10, fech[i] + 40, fech[i] - 40, fech[i], 500, 5, 0) for i in range(n)]
    return np.array(linhas, dtype=[("time", "<i8"), ("open", "<f8"), ("high", "<f8"), ("low", "<f8"),
                                   ("close", "<f8"), ("tick_volume", "<u8"), ("spread", "<i4"), ("real_volume", "<u8")])


def test_converter_taxas_sem_nan_e_com_sinais():
    df = AdaptadorMT5.converter_taxas(_rates_falsas())
    assert df.isna().sum().sum() == 0
    assert df.index.is_monotonic_increasing and df.index.name == "tempo"
    assert (df["volume"] > 0).all()  # real_volume zerado -> usa tick_volume
    assert ind.atr(df, 14).notna().sum() > 500
    total_sinais = sum(int((e.sinais_limpos(df) != 0).sum()) for e in construir_catalogo()[:20])
    assert total_sinais > 0
