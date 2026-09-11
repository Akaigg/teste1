"""Estratégias de rompimento (breakout)."""
from __future__ import annotations

from dominio import indicadores as ind
from dominio.estrategias.base import EstrategiaBase, cruzou_acima, cruzou_abaixo, entrou_em, montar_sinais


class RompimentoDonchian(EstrategiaBase):
    identificador = "donchian"
    familia = "rompimento"
    descricao = "Fechamento rompe a máxima/mínima das últimas N barras (canal de Donchian)."
    stop_atr_padrao, alvo_atr_padrao = 2.0, 4.0

    def gerar_sinais(self, df):
        sup, inf, _ = ind.donchian(df, self.p("periodo"))
        f = df["fechamento"]
        return montar_sinais(entrou_em(f > sup), entrou_em(f < inf))


class RompimentoAberturaDia(EstrategiaBase):
    identificador = "abertura_dia"
    familia = "rompimento"
    descricao = "Rompimento da faixa formada nas primeiras N barras do dia (opening range breakout)."
    stop_atr_padrao, alvo_atr_padrao = 1.5, 3.0

    def gerar_sinais(self, df):
        n = self.p("barras")
        dia = df.index.normalize()
        numero = df.groupby(dia).cumcount()
        alta_faixa = df["maxima"].where(numero < n).groupby(dia).transform("max")
        baixa_faixa = df["minima"].where(numero < n).groupby(dia).transform("min")
        f = df["fechamento"]
        apos = numero >= n
        return montar_sinais(entrou_em(apos & (f > alta_faixa)), entrou_em(apos & (f < baixa_faixa)))


class SqueezeBollinger(EstrategiaBase):
    identificador = "squeeze_bollinger"
    familia = "rompimento"
    descricao = "Compressão das bandas (largura mínima em N barras) seguida de rompimento."
    stop_atr_padrao, alvo_atr_padrao = 1.5, 3.0

    def gerar_sinais(self, df):
        media, sup, inf = ind.bollinger(df["fechamento"], self.p("periodo"), self.p("desvio"))
        largura = (sup - inf) / media
        comprimido = largura.shift(1) <= largura.shift(1).rolling(self.p("lookback")).min()
        f = df["fechamento"]
        return montar_sinais(comprimido & cruzou_acima(f, sup), comprimido & cruzou_abaixo(f, inf))


class RompimentoKeltner(EstrategiaBase):
    identificador = "keltner"
    familia = "rompimento"
    descricao = "Fechamento rompe o canal de Keltner."
    stop_atr_padrao, alvo_atr_padrao = 2.0, 3.0

    def gerar_sinais(self, df):
        _, sup, inf = ind.keltner(df, self.p("periodo"), self.p("mult"))
        f = df["fechamento"]
        return montar_sinais(cruzou_acima(f, sup), cruzou_abaixo(f, inf))


class RompimentoComVolume(EstrategiaBase):
    identificador = "rompimento_volume"
    familia = "rompimento"
    descricao = "Rompimento da máxima/mínima de N barras confirmado por volume acima da média."
    stop_atr_padrao, alvo_atr_padrao = 2.0, 3.0

    def gerar_sinais(self, df):
        sup, inf, _ = ind.donchian(df, self.p("periodo"))
        vol_forte = df["volume"] > self.p("mult_volume") * ind.sma(df["volume"], self.p("periodo"))
        f = df["fechamento"]
        return montar_sinais(entrou_em(f > sup) & vol_forte, entrou_em(f < inf) & vol_forte)


class FalsoRompimento(EstrategiaBase):
    identificador = "falso_rompimento"
    familia = "rompimento"
    descricao = "Preço rompe o canal e volta para dentro na barra seguinte: opera a reversão."
    stop_atr_padrao, alvo_atr_padrao = 1.5, 2.0

    def gerar_sinais(self, df):
        sup, inf, _ = ind.donchian(df, self.p("periodo"))
        f = df["fechamento"]
        rompeu_cima = (df["maxima"].shift(1) > sup.shift(1)) & (f < sup)
        rompeu_baixo = (df["minima"].shift(1) < inf.shift(1)) & (f > inf)
        return montar_sinais(entrou_em(rompeu_baixo), entrou_em(rompeu_cima))


def registrar():
    e = []
    for p in [20, 55, 10]:
        e.append(RompimentoDonchian(periodo=p))
    for b in [3, 6, 12]:
        e.append(RompimentoAberturaDia(barras=b))
    for p, d, lb in [(20, 2.0, 100), (20, 2.0, 50)]:
        e.append(SqueezeBollinger(periodo=p, desvio=d, lookback=lb))
    for p, m in [(20, 1.5), (20, 2.0), (10, 1.5)]:
        e.append(RompimentoKeltner(periodo=p, mult=m))
    for p, mv in [(10, 1.5), (20, 1.5), (50, 2.0)]:
        e.append(RompimentoComVolume(periodo=p, mult_volume=mv))
    for p in [20, 10]:
        e.append(FalsoRompimento(periodo=p))
    return e
