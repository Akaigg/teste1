"""
Estratégias de DIVERGÊNCIA por pivôs confirmados: compara os dois últimos
fundos (ou topos) do preço com os do oscilador. Um pivô só é usado depois de
`k` barras de confirmação (sem olhar o futuro).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from dominio import indicadores as ind
from dominio.estrategias.base import EstrategiaBase, entrou_em, montar_sinais


def _oscilador(df: pd.DataFrame, tipo: str) -> pd.Series:
    f = df["fechamento"]
    if tipo == "macd":
        return ind.macd(f)[2]
    if tipo == "cci":
        return ind.cci(df, 20)
    return ind.rsi(f, 14)


class DivergenciaPivos(EstrategiaBase):
    identificador = "divergencia_pivos"
    familia = "divergencia"
    descricao = ("Divergência regular entre pivôs confirmados do preço e do oscilador (RSI, MACD ou CCI): fundo mais baixo no "
                 "preço com fundo mais alto no oscilador = compra (e o inverso). Exige swing ≥ 0.8 ATR entre os pivôs, "
                 "ADX abaixo do máximo (sem tendência forte) e candle de confirmação.")
    stop_atr_padrao, alvo_atr_padrao = 1.5, 2.5

    def gerar_sinais(self, df):
        f, mn, mx = df["fechamento"], df["minima"], df["maxima"]
        k = self.p("k")
        osc = _oscilador(df, self.p("oscilador"))
        a = ind.atr(df, 14)
        topos, fundos = ind.pivos(df, k, k)
        osc_no_fundo = osc.shift(k).where(fundos.notna())
        osc_no_topo = osc.shift(k).where(topos.notna())
        f_ult, f_pen = ind.ultimos_dois(fundos)
        of_ult, of_pen = ind.ultimos_dois(osc_no_fundo)
        t_ult, t_pen = ind.ultimos_dois(topos)
        ot_ult, ot_pen = ind.ultimos_dois(osc_no_topo)
        adx, _, _ = ind.adx(df, 14)
        sem_tendencia_forte = adx < self.p("adx_max")
        # a divergência "nasce" na barra de confirmação do pivô mais recente
        novo_fundo, novo_topo = fundos.notna(), topos.notna()
        div_alta = novo_fundo & (f_ult < f_pen) & (of_ult > of_pen) & ((t_ult - f_ult) >= 0.8 * a)
        div_baixa = novo_topo & (t_ult > t_pen) & (ot_ult < ot_pen) & ((t_ult - f_ult) >= 0.8 * a)
        # janela de gatilho: até `k` barras após a confirmação, candle a favor
        janela_alta = div_alta.astype(float).rolling(k + 1).max().fillna(0).astype(bool)
        janela_baixa = div_baixa.astype(float).rolling(k + 1).max().fillna(0).astype(bool)
        compras = entrou_em(janela_alta & (f > f.shift(1)) & (f > df["abertura"]) & sem_tendencia_forte)
        vendas = entrou_em(janela_baixa & (f < f.shift(1)) & (f < df["abertura"]) & sem_tendencia_forte)
        return montar_sinais(compras, vendas)


def registrar():
    e = []
    for osc, k, adx in [("rsi", 5, 35), ("rsi", 3, 30), ("macd", 5, 35), ("macd", 8, 40), ("cci", 5, 35)]:
        e.append(DivergenciaPivos(oscilador=osc, k=k, adx_max=adx))
    return e
