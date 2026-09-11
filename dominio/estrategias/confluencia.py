"""
Estratégias de CONFLUÊNCIA: exigem que leituras independentes (dois timeframes
superiores, ou vários osciladores) apontem para o mesmo lado antes do gatilho
no timeframe operado.

Os timeframes superiores são reamostrados por tempo e SÓ usam barras superiores
já concluídas (`alinhar_superior`), sem olhar o futuro.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from dominio import indicadores as ind
from dominio.estrategias.base import (EstrategiaBase, cruzou_abaixo, cruzou_acima, entrou_em, limitar, montar_sinais,
                                      pontuacao_ponderada)


def vies_timeframe(df_sup: pd.DataFrame, indice_base) -> pd.Series:
    """Viés [-1, 1] de um timeframe superior: sinal da inclinação da EMA20, RSI14 vs 50 e histograma MACD."""
    f = df_sup["fechamento"]
    e20 = ind.ema(f, 20)
    votos = (np.sign(e20 - e20.shift(3)) + np.sign(ind.rsi(f, 14) - 50) + np.sign(ind.macd(f)[2])) / 3.0
    return ind.alinhar_superior(votos, indice_base)


class ConfluenciaMultiTimeframe(EstrategiaBase):
    identificador = "confluencia_tf"
    familia = "confluencia"
    descricao = ("Dois timeframes superiores (x fator1 e x fator2) precisam concordar (EMA20 inclinada, RSI e MACD do mesmo "
                 "lado, ≥2 de 3 em cada um). No timeframe operado, entra no pullback: RSI(7) recupera 40/60 com o preço "
                 "do lado certo da EMA20 e candle a favor.")
    stop_atr_padrao, alvo_atr_padrao = 1.5, 3.0

    def _vieses(self, df):
        return (vies_timeframe(ind.reamostrar_superior(df, self.p("fator1")), df.index),
                vies_timeframe(ind.reamostrar_superior(df, self.p("fator2")), df.index))

    def vies(self, df):
        v1, v2 = self._vieses(df)
        return (v1 + v2) / 2.0

    def barras_minimas(self) -> int:
        # o executor usa 2x este valor: garante ~300 barras concluídas do timeframe superior para as EMAs convergirem
        return max(super().barras_minimas(), int(self.p("fator2")) * 150)

    def gerar_sinais(self, df):
        f, ab = df["fechamento"], df["abertura"]
        v1, v2 = self._vieses(df)
        e20 = ind.ema(f, 20)
        rsi7 = ind.rsi(f, 7)
        # votos em {-1, -1/3, 1/3, 1}: ≥ 0.3 significa pelo menos 2 dos 3 medidores a favor
        compras = (v1 >= 0.3) & (v2 >= 0.3) & (f > e20) & (f > ab) & cruzou_acima(rsi7, 40)
        vendas = (v1 <= -0.3) & (v2 <= -0.3) & (f < e20) & (f < ab) & cruzou_abaixo(rsi7, 60)
        return montar_sinais(compras, vendas)


class ConfluenciaOsciladores(EstrategiaBase):
    identificador = "confluencia_osciladores"
    familia = "confluencia"
    descricao = ("Cinco osciladores normalizados (RSI, Estocástico, CCI, Williams %R, MFI) formam uma pontuação de extremo. "
                 "Entra quando a pontuação está extrema, há divergência com o preço (preço faz nova mínima em N barras e "
                 "a pontuação não) e o candle vira a favor.")
    stop_atr_padrao, alvo_atr_padrao = 1.5, 2.5

    def _pontuacao(self, df):
        f = df["fechamento"]
        k, _ = ind.estocastico(df, 14, 3)
        return pontuacao_ponderada({
            "rsi": (limitar((ind.rsi(f, 14) - 50) / 50.0), 1.0),
            "estocastico": (limitar((k - 50) / 50.0), 1.0),
            "cci": (limitar(ind.cci(df, 20) / 200.0), 1.0),
            "williams": (limitar((ind.williams_r(df, 14) + 50) / 50.0), 1.0),
            "mfi": (limitar((ind.mfi(df, 14) - 50) / 50.0), 1.0),
        })

    def vies(self, df):
        return -self._pontuacao(df)  # extremo negativo (sobrevenda) = viés comprador

    def gerar_sinais(self, df):
        f, mn, mx = df["fechamento"], df["minima"], df["maxima"]
        s = self._pontuacao(df)
        n, lim = self.p("barras_divergencia"), self.p("limiar")
        min_atual, min_anterior = mn.rolling(n).min(), mn.shift(n).rolling(n).min()
        max_atual, max_anterior = mx.rolling(n).max(), mx.shift(n).rolling(n).max()
        s_min_atual, s_min_anterior = s.rolling(n).min(), s.shift(n).rolling(n).min()
        s_max_atual, s_max_anterior = s.rolling(n).max(), s.shift(n).rolling(n).max()
        div_alta = (min_atual < min_anterior) & (s_min_atual > s_min_anterior)
        div_baixa = (max_atual > max_anterior) & (s_max_atual < s_max_anterior)
        compras = entrou_em((s <= -lim) & div_alta & (f > f.shift(1)))
        vendas = entrou_em((s >= lim) & div_baixa & (f < f.shift(1)))
        return montar_sinais(compras, vendas)


def registrar():
    e = []
    for f1, f2 in [(3, 12), (4, 16), (2, 6), (6, 24)]:
        e.append(ConfluenciaMultiTimeframe(fator1=f1, fator2=f2))
    for lim, n in [(0.5, 10), (0.6, 20), (0.4, 8)]:
        e.append(ConfluenciaOsciladores(limiar=lim, barras_divergencia=n))
    return e
