"""
Provedor de replay: entrega candles históricos progressivamente, um por
chamada, para testar o executor (modo simulado) com dados de CSV ou
sintéticos sem precisar de mercado aberto.
"""
from __future__ import annotations

import pandas as pd


class ProvedorReplay:
    def __init__(self, provedor_base, total_barras: int, aquecimento: int = 500):
        self.base = provedor_base
        self.total_barras = total_barras
        self.aquecimento = aquecimento
        self._df = None
        self._posicao = 0
        self.terminou = False

    def obter_candles(self, ativo: str, timeframe: str, quantidade: int) -> pd.DataFrame:
        if self._df is None:
            self._df = self.base.obter_candles(ativo, timeframe, self.total_barras)
            self._posicao = min(len(self._df), max(self.aquecimento, quantidade))
        self._posicao += 1
        if self._posicao >= len(self._df):
            self.terminou = True
            self._posicao = len(self._df)
        return self._df.iloc[max(0, self._posicao - quantidade): self._posicao]
