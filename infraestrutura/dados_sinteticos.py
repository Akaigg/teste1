"""
Gerador de candles sintéticos (passeio aleatório com regimes) para testar o
robô sem conexão ao MT5. NÃO use para tomar decisões reais.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

_MINUTOS = {"M1": 1, "M5": 5, "M15": 15, "M30": 30, "H1": 60, "H4": 240, "D1": 1440}


class ProvedorSintetico:
    def __init__(self, semente: int = 42, preco_inicial: float = 100000.0):
        self.semente = semente
        self.preco_inicial = preco_inicial

    def obter_candles(self, ativo: str, timeframe: str, quantidade: int) -> pd.DataFrame:
        rng = np.random.default_rng(self.semente)
        minutos = _MINUTOS.get(timeframe.upper(), 5)
        barras_por_dia = max(1, int(8.5 * 60 / minutos)) if minutos < 1440 else 1
        dias = int(np.ceil(quantidade / barras_por_dia)) + 1
        inicio = pd.Timestamp("2024-01-02 09:00")
        tempos = []
        dia = inicio
        while len(tempos) < quantidade:
            if dia.weekday() < 5:
                for k in range(barras_por_dia):
                    tempos.append(dia + pd.Timedelta(minutes=k * minutos))
            dia += pd.Timedelta(days=1)
        tempos = pd.DatetimeIndex(tempos[:quantidade])

        n = len(tempos)
        regime = np.zeros(n)                                          # deriva lenta e estacionária (tendências curtas)
        for k in range(1, n):
            regime[k] = 0.93 * regime[k - 1] + rng.normal(0, 0.00007)
        vol = 0.0008 * (1 + 0.5 * np.sin(np.arange(n) / 300.0))       # volatilidade cíclica
        retornos = regime + rng.normal(0, 1, n) * vol
        log_preco = np.cumsum(retornos)
        log_preco -= 0.0005 * np.cumsum(log_preco - np.mean(log_preco)) / n  # evita fuga de longo prazo
        fechamento = self.preco_inicial * np.exp(log_preco - log_preco[0])
        abertura = np.concatenate([[fechamento[0]], fechamento[:-1]]) * (1 + rng.normal(0, 0.0002, n))
        amplitude = np.abs(rng.normal(0, 1, n)) * vol * fechamento
        maxima = np.maximum(abertura, fechamento) + amplitude * rng.uniform(0.2, 1.0, n)
        minima = np.minimum(abertura, fechamento) - amplitude * rng.uniform(0.2, 1.0, n)
        volume = (rng.gamma(2.0, 500, n) * (1 + 5 * np.abs(retornos) / vol.mean())).astype(int)

        df = pd.DataFrame({"abertura": abertura, "maxima": maxima, "minima": minima,
                           "fechamento": fechamento, "volume": volume}, index=tempos)
        df.index.name = "tempo"
        return df.round(0)
