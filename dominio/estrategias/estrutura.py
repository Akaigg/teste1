"""
Estratégias de ESTRUTURA DE MERCADO (price action quantificado): sequência de
topos/fundos confirmados (HH/HL x LH/LL), rompimento de estrutura com volume e
uma pontuação composta da força dos candles com contexto.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from dominio import indicadores as ind
from dominio.estrategias.base import (EstrategiaBase, concordancia, cruzou_abaixo, cruzou_acima, entrou_em, limitar,
                                      montar_sinais, normalizar, pontuacao_ponderada)


class EstruturaMercado(EstrategiaBase):
    identificador = "estrutura_mercado"
    familia = "estrutura_mercado"
    descricao = ("Pivôs confirmados definem a estrutura: topos e fundos ascendentes (HH/HL) = alta; descendentes (LH/LL) = "
                 "baixa. Entra no rompimento do último topo (ou fundo) a favor da estrutura, com o swing ≥ 1 ATR, "
                 "volume acima da média e ADX confirmando direção.")
    stop_atr_padrao, alvo_atr_padrao = 1.5, 3.0

    def gerar_sinais(self, df):
        f, v = df["fechamento"], df["volume"]
        k = self.p("k")
        a = ind.atr(df, 14)
        topos, fundos = ind.pivos(df, k, k)
        t_ult, t_pen = ind.ultimos_dois(topos)
        f_ult, f_pen = ind.ultimos_dois(fundos)
        estrutura_alta = (t_ult > t_pen) & (f_ult > f_pen)
        estrutura_baixa = (t_ult < t_pen) & (f_ult < f_pen)
        swing_ok = (t_ult - f_ult).abs() >= self.p("swing_atr") * a
        volume_ok = v >= self.p("mult_volume") * ind.sma(v, 20)
        _, dip, dim = ind.adx(df, 14)
        compras = estrutura_alta & swing_ok & volume_ok & (dip > dim) & cruzou_acima(f, t_ult)
        vendas = estrutura_baixa & swing_ok & volume_ok & (dim > dip) & cruzou_abaixo(f, f_ult)
        return montar_sinais(compras, vendas)


class ForcaCandleComposta(EstrategiaBase):
    identificador = "forca_candle"
    familia = "estrutura_mercado"
    descricao = ("Pontuação composta do candle e contexto: corpo relativo com sinal (1.0), posição do fechamento na "
                 "amplitude (1.0), momentum de 3 barras/ATR (1.0), volume relativo com direção (0.5) e distância da EMA50 "
                 "(1.0). Só considera candles com amplitude ≥ fração do ATR; entra no cruzamento do limiar.")
    stop_atr_padrao, alvo_atr_padrao = 1.5, 2.5

    def _componentes(self, df):
        f, ab, mx, mn, v = df["fechamento"], df["abertura"], df["maxima"], df["minima"], df["volume"]
        a = ind.atr(df, 14)
        amp = (mx - mn).replace(0, np.nan)
        direcao = np.sign(f - ab)
        return {
            "corpo": (limitar((f - ab) / amp * 1.5), 1.0),
            "posicao": (limitar(2 * (f - mn) / amp - 1), 1.0),
            "momentum": (normalizar((f - f.shift(3)) / a, 1.5), 1.0),
            "volume": (limitar(v / ind.sma(v, 20) - 1, 0, 1) * direcao, 0.5),
            "contexto": (normalizar((f - ind.ema(f, 50)) / a, 2.0), 1.0),
        }

    def vies(self, df):
        return pontuacao_ponderada(self._componentes(df))

    def gerar_sinais(self, df):
        mx, mn = df["maxima"], df["minima"]
        a = ind.atr(df, 14)
        comp = self._componentes(df)
        score = pontuacao_ponderada(comp)
        relevante = (mx - mn) >= self.p("amplitude_atr") * a
        lim = self.p("limiar")
        compras = cruzou_acima(score, lim) & relevante & (concordancia(comp, 1) >= 4)
        vendas = cruzou_abaixo(score, -lim) & relevante & (concordancia(comp, -1) >= 4)
        return montar_sinais(compras, vendas)


def registrar():
    e = []
    for k, sw, mv in [(3, 1.0, 1.2), (5, 1.0, 1.0), (8, 1.5, 1.2), (5, 2.0, 1.5)]:
        e.append(EstruturaMercado(k=k, swing_atr=sw, mult_volume=mv))
    for amp, lim in [(0.8, 0.50), (1.0, 0.55), (0.6, 0.45)]:
        e.append(ForcaCandleComposta(amplitude_atr=amp, limiar=lim))
    return e
