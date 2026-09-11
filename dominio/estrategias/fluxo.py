"""
Estratégias de FLUXO DE VOLUME: pontuação ponderada de medidores de pressão
compradora/vendedora (CMF, MFI, OBV, Force Index, delta agressor, VWAP) e
operações nas bandas de desvio da VWAP diária.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from dominio import indicadores as ind
from dominio.estrategias.base import (EstrategiaBase, concordancia, cruzou_abaixo, cruzou_acima, entrou_em, limitar,
                                      montar_sinais, normalizar, pontuacao_ponderada)


class FluxoPonderado(EstrategiaBase):
    identificador = "fluxo_ponderado"
    familia = "fluxo_volume"
    descricao = ("Pontuação de fluxo com 6 componentes: CMF (1.0), MFI (1.0), variação do OBV relativa ao volume (1.5), "
                 "Force Index normalizado (1.0), delta agressor (posição do fechamento x volume, 1.5) e preço x VWAP (0.5). "
                 "Entra quando o fluxo cruza o limiar com ≥4 componentes concordando e o preço do lado certo da EMA20.")
    stop_atr_padrao, alvo_atr_padrao = 1.5, 3.0

    def _componentes(self, df):
        f, v = df["fechamento"], df["volume"]
        a = ind.atr(df, 14)
        n = self.p("periodo")
        obv = ind.obv(df)
        delta_obv = (obv - obv.shift(n)) / v.rolling(n).sum().replace(0, np.nan)
        fi = ind.force_index(df, 13) / (a * ind.sma(v, 20)).replace(0, np.nan)
        return {
            "cmf": (limitar(ind.cmf(df, 20) * 4.0), 1.0),
            "mfi": (limitar((ind.mfi(df, 14) - 50) / 30.0), 1.0),
            "obv": (limitar(delta_obv), 1.5),
            "force": (normalizar(fi, 0.5), 1.0),
            "delta": (limitar(ind.delta_volume(df, n) * 2.0), 1.5),
            "vwap": (normalizar((f - ind.vwap(df)) / a, 1.0), 0.5),
        }

    def vies(self, df):
        return pontuacao_ponderada(self._componentes(df))

    def gerar_sinais(self, df):
        f = df["fechamento"]
        comp = self._componentes(df)
        score = pontuacao_ponderada(comp)
        e20 = ind.ema(f, 20)
        lim = self.p("limiar")
        compras = cruzou_acima(score, lim) & (f > e20) & (concordancia(comp, 1) >= 4)
        vendas = cruzou_abaixo(score, -lim) & (f < e20) & (concordancia(comp, -1) >= 4)
        return montar_sinais(compras, vendas)


class BandasVWAP(EstrategiaBase):
    identificador = "bandas_vwap"
    familia = "fluxo_volume"
    descricao = ("VWAP diária com bandas de desvio ponderado por volume. Modo 'reversao': preço extrapola a banda e volta "
                 "para dentro com MFI em extremo e delta agressor virando. Modo 'continuacao': pullback até a VWAP a "
                 "favor da tendência do dia com fluxo (CMF e delta) positivo. Ignora as primeiras barras do dia.")
    stop_atr_padrao, alvo_atr_padrao = 1.5, 2.0

    def gerar_sinais(self, df):
        f, mn, mx, ab = df["fechamento"], df["minima"], df["maxima"], df["abertura"]
        vwap, sup, inf, dp = ind.bandas_vwap(df, self.p("desvios"))
        maduro = ind.barra_do_dia(df) >= self.p("barras_iniciais")
        delta = ind.delta_volume(df, 5)
        if self.p("modo") == "reversao":
            mfi = ind.mfi(df, 14)
            compras = cruzou_acima(f, inf) & (mfi < 35) & (delta > delta.shift(1)) & maduro
            vendas = cruzou_abaixo(f, sup) & (mfi > 65) & (delta < delta.shift(1)) & maduro
        else:
            cmf = ind.cmf(df, 20)
            e50 = ind.ema(f, 50)
            tocou_cima = (mn <= vwap) & (f > vwap) & (f > ab) & (f > e50)
            tocou_baixo = (mx >= vwap) & (f < vwap) & (f < ab) & (f < e50)
            compras = entrou_em(tocou_cima & (cmf > 0.05) & (delta > 0) & maduro)
            vendas = entrou_em(tocou_baixo & (cmf < -0.05) & (delta < 0) & maduro)
        return montar_sinais(compras, vendas)


def registrar():
    e = []
    for n, lim in [(10, 0.30), (20, 0.35), (5, 0.40)]:
        e.append(FluxoPonderado(periodo=n, limiar=lim))
    for modo, d, bi in [("reversao", 2.0, 6), ("reversao", 2.5, 12), ("continuacao", 1.0, 6), ("continuacao", 1.5, 12)]:
        e.append(BandasVWAP(modo=modo, desvios=d, barras_iniciais=bi))
    return e
