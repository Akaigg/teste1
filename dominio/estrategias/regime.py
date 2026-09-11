"""
Estratégias ADAPTATIVAS AO REGIME: classificam o mercado (tendência, lateral,
compressão/expansão de volatilidade) por votação de vários medidores e aplicam
a lógica de entrada adequada a cada regime. Os filtros têm memória finita
(janelas móveis), então o executor ao vivo reproduz o backtest.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from dominio import indicadores as ind
from dominio.estrategias.base import (EstrategiaBase, cruzou_abaixo, cruzou_acima, entrou_em, limitar, montar_sinais,
                                      normalizar, pontuacao_ponderada)


def classificar_regime(df: pd.DataFrame, periodo: int):
    """Votação de 3 medidores. Retorna (tendencia, lateral) booleanos, mutuamente exclusivos."""
    f = df["fechamento"]
    er = ind.eficiencia_kaufman(f, periodo)
    adx, _, _ = ind.adx(df, 14)
    chop = ind.choppiness(df, 14)
    votos_tendencia = (er > 0.30).astype(int) + (adx > 22).astype(int) + (chop < 50).astype(int)
    votos_lateral = (er < 0.20).astype(int) + (adx < 20).astype(int) + (chop > 55).astype(int)
    tendencia = (votos_tendencia >= 2) & (votos_lateral < 2)
    lateral = (votos_lateral >= 2) & (votos_tendencia < 2)
    return tendencia, lateral


class RegimeAdaptativo(EstrategiaBase):
    identificador = "regime_adaptativo"
    familia = "regime_adaptativo"
    descricao = ("Classifica o regime por votação de Efficiency Ratio, ADX e Choppiness. Em TENDÊNCIA opera pullback "
                 "à EMA curta a favor da EMA longa inclinada (com RSI curto recuperando); em LATERAL opera a volta "
                 "para dentro das Bandas de Bollinger com RSI confirmando. Fora dos dois regimes não opera.")
    stop_atr_padrao, alvo_atr_padrao = 1.5, 2.5

    def gerar_sinais(self, df):
        f, ab, mx, mn = df["fechamento"], df["abertura"], df["maxima"], df["minima"]
        a = ind.atr(df, 14)
        tendencia, lateral = classificar_regime(df, self.p("periodo_regime"))
        curta, longa = ind.ema(f, self.p("curta")), ind.ema(f, self.p("longa"))
        incl_longa = ind.inclinacao(longa, 10) / a
        rsi5 = ind.rsi(f, 5)
        alta = (curta > longa) & (incl_longa > 0.02)
        baixa = (curta < longa) & (incl_longa < -0.02)
        # pullback: tocou a EMA curta nas últimas 3 barras e fechou de volta a favor, com RSI curto virando
        tocou_curta_cima = (mn <= curta).astype(float).rolling(3).max().fillna(0).astype(bool)
        tocou_curta_baixo = (mx >= curta).astype(float).rolling(3).max().fillna(0).astype(bool)
        compra_tend = tendencia & alta & tocou_curta_cima & (f > curta) & (f > ab) & cruzou_acima(rsi5, 45)
        venda_tend = tendencia & baixa & tocou_curta_baixo & (f < curta) & (f < ab) & cruzou_abaixo(rsi5, 55)

        _, sup, inf = ind.bollinger(f, 20, 2.0)
        rsi14 = ind.rsi(f, 14)
        compra_lat = lateral & cruzou_acima(f, inf) & (rsi14 < 40)
        venda_lat = lateral & cruzou_abaixo(f, sup) & (rsi14 > 60)
        return montar_sinais(compra_tend | compra_lat, venda_tend | venda_lat)


class ExpansaoVolatilidade(EstrategiaBase):
    identificador = "expansao_volatilidade"
    familia = "regime_adaptativo"
    descricao = ("Compressão (largura de Bollinger no percentil baixo e Bollinger dentro de Keltner) seguida de expansão "
                 "(largura e ATR crescendo). A direção vem de uma pontuação de 4 componentes: distância da SMA, "
                 "histograma MACD, DI+/DI- e posição no canal de Donchian; entra quando a pontuação supera o limiar.")
    stop_atr_padrao, alvo_atr_padrao = 1.5, 3.0

    def _direcao(self, df):
        f = df["fechamento"]
        a = ind.atr(df, 14)
        _, _, hist = ind.macd(f)
        _, dip, dim = ind.adx(df, 14)
        sup, inf, _ = ind.donchian(df, 20)
        posicao = (f - inf) / (sup - inf).replace(0, np.nan)
        return pontuacao_ponderada({
            "sma": (normalizar((f - ind.sma(f, 20)) / a, 1.0), 1.0),
            "macd": (normalizar(hist / a, 0.5), 1.0),
            "di": (limitar((dip - dim) / (dip + dim).replace(0, np.nan)), 1.0),
            "donchian": (limitar((posicao - 0.5) * 2.0), 1.0),
        })

    def vies(self, df):
        return self._direcao(df)

    def gerar_sinais(self, df):
        f = df["fechamento"]
        p = self.p("periodo_bb")
        media, sup, inf = ind.bollinger(f, p, 2.0)
        _, ksup, kinf = ind.keltner(df, p, 1.5)
        largura = (sup - inf) / media
        pct_largura = ind.percentil(largura, self.p("lookback"))
        dentro_keltner = (sup < ksup) & (inf > kinf)
        houve_compressao = ((pct_largura < 0.20) & dentro_keltner).astype(float).rolling(
            self.p("barras_apos")).max().fillna(0).astype(bool)
        a = ind.atr(df, 14)
        expandindo = (largura > largura.shift(1)) & (largura.shift(1) > largura.shift(2)) & (a > a.shift(2))
        score = self._direcao(df)
        lim = self.p("limiar")
        compras = entrou_em(houve_compressao & expandindo & (score >= lim) & (f > sup.shift(1)))
        vendas = entrou_em(houve_compressao & expandindo & (score <= -lim) & (f < inf.shift(1)))
        return montar_sinais(compras, vendas)


def registrar():
    e = []
    for pr, c, l in [(20, 9, 50), (30, 12, 100), (14, 8, 34), (20, 21, 200)]:
        e.append(RegimeAdaptativo(periodo_regime=pr, curta=c, longa=l))
    for p, lb, ba, lim in [(20, 100, 6, 0.40), (20, 50, 4, 0.50), (14, 120, 8, 0.35)]:
        e.append(ExpansaoVolatilidade(periodo_bb=p, lookback=lb, barras_apos=ba, limiar=lim))
    return e
