"""
Estratégias de PONTUAÇÃO PONDERADA: vários indicadores são normalizados para o
intervalo [-1, 1] (positivo = altista), recebem pesos e a média ponderada vira
uma pontuação contínua. A entrada ocorre quando a pontuação cruza um limiar,
com filtros de regime de volatilidade e concordância mínima entre componentes.

Todas expõem `vies(df)` (a própria pontuação), reutilizado pelo ensemble.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from dominio import indicadores as ind
from dominio.estrategias.base import (EstrategiaBase, concordancia, cruzou_abaixo, cruzou_acima, entrou_em,
                                      limitar, montar_sinais, normalizar, pontuacao_ponderada)


def _regime_volatilidade_ok(df: pd.DataFrame, minimo: float = 0.10, maximo: float = 0.95, janela: int = 200) -> pd.Series:
    """Evita mercado morto (ATR no fundo do histórico) e pânico (ATR no topo)."""
    pct = ind.percentil(ind.atr(df, 14), janela)
    return (pct >= minimo) & (pct <= maximo)


class ScoreTendencia(EstrategiaBase):
    identificador = "score_tendencia"
    familia = "pontuacao_ponderada"
    descricao = ("Pontuação ponderada de 6 indicadores de tendência: distância entre EMAs (1.5), inclinação da EMA "
                 "média (1.0), histograma MACD (1.0), DI+/DI- ponderado pelo ADX (1.0), RSI (0.5) e preço x VWAP (0.5). "
                 "Entra quando a pontuação cruza ±limiar com ≥4 componentes concordando e ATR em regime normal.")
    stop_atr_padrao, alvo_atr_padrao = 2.0, 3.0

    def _componentes(self, df):
        f = df["fechamento"]
        a = ind.atr(df, 14)
        curta, media, longa = ind.ema(f, self.p("curta")), ind.ema(f, self.p("media")), ind.ema(f, self.p("longa"))
        adx, dip, dim = ind.adx(df, 14)
        _, _, hist = ind.macd(f)
        return {
            "emas": (normalizar((curta - longa) / a, 1.0), 1.5),
            "inclinacao": (normalizar(ind.inclinacao(media, 10) * 10 / a, 1.0), 1.0),
            "macd": (normalizar(hist / a, 0.5), 1.0),
            "di": (limitar((dip - dim) / (dip + dim).replace(0, np.nan)) * limitar(adx / 25.0, 0, 1), 1.0),
            "rsi": (limitar((ind.rsi(f, 14) - 50) / 25.0), 0.5),
            "vwap": (normalizar((f - ind.vwap(df)) / a, 1.0), 0.5),
        }

    def vies(self, df):
        return pontuacao_ponderada(self._componentes(df))

    def gerar_sinais(self, df):
        comp = self._componentes(df)
        score = pontuacao_ponderada(comp)
        lim = self.p("limiar")
        ok = _regime_volatilidade_ok(df)
        compras = cruzou_acima(score, lim) & (concordancia(comp, 1) >= 4) & ok
        vendas = cruzou_abaixo(score, -lim) & (concordancia(comp, -1) >= 4) & ok
        return montar_sinais(compras, vendas)


class ScoreReversao(EstrategiaBase):
    identificador = "score_reversao"
    familia = "pontuacao_ponderada"
    descricao = ("Pontuação de sobrevenda/sobrecompra com 6 componentes: z-score (1.5), RSI curto (1.0), %B de Bollinger (1.0), "
                 "Williams %R (0.5), CCI (0.5) e distância da VWAP (0.5). Entra na reversão só quando a pontuação "
                 "extrapola o limiar, o candle vira a favor e o ADX indica mercado sem tendência forte.")
    stop_atr_padrao, alvo_atr_padrao = 1.5, 2.0

    def _componentes(self, df):
        f = df["fechamento"]
        a = ind.atr(df, 14)
        media, sup, inf = ind.bollinger(f, 20, 2.0)
        pct_b = (f - inf) / (sup - inf).replace(0, np.nan)
        return {
            "zscore": (normalizar(-ind.zscore(f, self.p("periodo_z")), 2.0), 1.5),
            "rsi_curto": (limitar((50 - ind.rsi(f, 3)) / 40.0), 1.0),
            "bollinger": (limitar((0.5 - pct_b) * 2.0), 1.0),
            "williams": (limitar((-50 - ind.williams_r(df, 14)) / 40.0), 0.5),
            "cci": (limitar(-ind.cci(df, 20) / 150.0), 0.5),
            "vwap": (normalizar(-(f - ind.vwap(df)) / a, 1.5), 0.5),
        }

    def vies(self, df):
        return pontuacao_ponderada(self._componentes(df))

    def gerar_sinais(self, df):
        f = df["fechamento"]
        comp = self._componentes(df)
        score = pontuacao_ponderada(comp)
        lim = self.p("limiar")
        adx, _, _ = ind.adx(df, 14)
        lateral = adx < self.p("adx_max")
        ok = _regime_volatilidade_ok(df, maximo=0.90)
        virou_cima = (f > f.shift(1)) & (f > df["abertura"])
        virou_baixo = (f < f.shift(1)) & (f < df["abertura"])
        compras = entrou_em((score.shift(1) >= lim) & virou_cima & lateral & ok & (concordancia(comp, 1) >= 4))
        vendas = entrou_em((score.shift(1) <= -lim) & virou_baixo & lateral & ok & (concordancia(comp, -1) >= 4))
        return montar_sinais(compras, vendas)


class ScoreMomentumVolume(EstrategiaBase):
    identificador = "score_momentum_volume"
    familia = "pontuacao_ponderada"
    descricao = ("Momentum confirmado por fluxo: ROC em 3 horizontes normalizado pela volatilidade (1.5), TSI (1.0), "
                 "CMF (1.0), MFI (0.5), variação do OBV relativa ao volume (1.0) e eficiência de Kaufman com direção (1.0). "
                 "Entra no cruzamento do limiar com volume acima da média.")
    stop_atr_padrao, alvo_atr_padrao = 2.0, 3.0

    def _componentes(self, df):
        f = df["fechamento"]
        a = ind.atr(df, 14)
        vol_rel = a / f * 100
        rocs = [normalizar(ind.roc(f, k) / (vol_rel * np.sqrt(k)), 1.0) for k in (5, 10, 20)]
        roc_medio = pd.concat(rocs, axis=1).mean(axis=1, skipna=False)
        n = self.p("periodo")
        obv = ind.obv(df)
        delta_obv = (obv - obv.shift(n)) / df["volume"].rolling(n).sum().replace(0, np.nan)
        direcao = np.sign(f - f.shift(n))
        return {
            "roc": (roc_medio, 1.5),
            "tsi": (limitar(ind.tsi(f) / 30.0), 1.0),
            "cmf": (limitar(ind.cmf(df, 20) * 4.0), 1.0),
            "mfi": (limitar((ind.mfi(df, 14) - 50) / 30.0), 0.5),
            "obv": (limitar(delta_obv), 1.0),
            "eficiencia": (limitar(ind.eficiencia_kaufman(f, n) * direcao), 1.0),
        }

    def vies(self, df):
        return pontuacao_ponderada(self._componentes(df))

    def gerar_sinais(self, df):
        comp = self._componentes(df)
        score = pontuacao_ponderada(comp)
        lim = self.p("limiar")
        volume_forte = df["volume"] >= self.p("mult_volume") * ind.sma(df["volume"], 20)
        ok = _regime_volatilidade_ok(df)
        compras = cruzou_acima(score, lim) & volume_forte & ok & (concordancia(comp, 1) >= 4)
        vendas = cruzou_abaixo(score, -lim) & volume_forte & ok & (concordancia(comp, -1) >= 4)
        return montar_sinais(compras, vendas)


def registrar():
    e = []
    for c, m, l, lim in [(9, 21, 55, 0.35), (12, 26, 100, 0.40), (20, 50, 200, 0.30), (5, 13, 34, 0.45)]:
        e.append(ScoreTendencia(curta=c, media=m, longa=l, limiar=lim))
    for pz, lim, adx in [(20, 0.45, 30), (30, 0.55, 25), (14, 0.40, 35), (50, 0.50, 30)]:
        e.append(ScoreReversao(periodo_z=pz, limiar=lim, adx_max=adx))
    for n, lim, mv in [(10, 0.30, 1.0), (20, 0.35, 1.2), (5, 0.40, 1.0)]:
        e.append(ScoreMomentumVolume(periodo=n, limiar=lim, mult_volume=mv))
    return e
