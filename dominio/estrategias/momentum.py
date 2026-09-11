"""Estratégias de momentum."""
from __future__ import annotations

from dominio import indicadores as ind
from dominio.estrategias.base import EstrategiaBase, cruzou_acima, cruzou_abaixo, entrou_em, montar_sinais


class ROCCruzamentoZero(EstrategiaBase):
    identificador = "roc_zero"
    familia = "momentum"
    descricao = "Rate of Change cruza a linha zero."
    stop_atr_padrao, alvo_atr_padrao = 2.0, 3.0

    def gerar_sinais(self, df):
        r = ind.roc(df["fechamento"], self.p("periodo"))
        return montar_sinais(cruzou_acima(r, 0), cruzou_abaixo(r, 0))


class TSICruzamento(EstrategiaBase):
    identificador = "tsi"
    familia = "momentum"
    descricao = "True Strength Index cruza sua linha de sinal."
    stop_atr_padrao, alvo_atr_padrao = 2.0, 3.0

    def gerar_sinais(self, df):
        t = ind.tsi(df["fechamento"], self.p("longo"), self.p("curto"))
        sinal = ind.ema(t, 7)
        return montar_sinais(cruzou_acima(t, sinal), cruzou_abaixo(t, sinal))


class AwesomeCruzamentoZero(EstrategiaBase):
    identificador = "awesome_zero"
    familia = "momentum"
    descricao = "Awesome Oscillator cruza a linha zero."
    stop_atr_padrao, alvo_atr_padrao = 2.0, 3.0

    def gerar_sinais(self, df):
        ao = ind.awesome(df, self.p("rapido"), self.p("lento"))
        return montar_sinais(cruzou_acima(ao, 0), cruzou_abaixo(ao, 0))


class AwesomePires(EstrategiaBase):
    identificador = "awesome_pires"
    familia = "momentum"
    descricao = "Padrão 'pires' do Awesome Oscillator: duas barras caindo e uma subindo acima de zero."
    stop_atr_padrao, alvo_atr_padrao = 1.5, 3.0

    def gerar_sinais(self, df):
        ao = ind.awesome(df, self.p("rapido"), self.p("lento"))
        d = ao.diff()
        compra = (ao > 0) & (d.shift(2) < 0) & (d.shift(1) < 0) & (d > 0)
        venda = (ao < 0) & (d.shift(2) > 0) & (d.shift(1) > 0) & (d < 0)
        return montar_sinais(compra, venda)


class RSICruzamento50(EstrategiaBase):
    identificador = "rsi_50"
    familia = "momentum"
    descricao = "RSI cruza a linha central de 50."
    stop_atr_padrao, alvo_atr_padrao = 2.0, 2.5

    def gerar_sinais(self, df):
        r = ind.rsi(df["fechamento"], self.p("periodo"))
        return montar_sinais(cruzou_acima(r, 50), cruzou_abaixo(r, 50))


class MACDHistogramaReversao(EstrategiaBase):
    identificador = "macd_histograma"
    familia = "momentum"
    descricao = "Histograma do MACD inverte a inclinação depois de dois passos na mesma direção."
    stop_atr_padrao, alvo_atr_padrao = 1.5, 2.5

    def gerar_sinais(self, df):
        _, _, hist = ind.macd(df["fechamento"], self.p("rapida"), self.p("lenta"), self.p("sinal"))
        d = hist.diff()
        compra = (hist < 0) & (d.shift(1) < 0) & (d > 0)
        venda = (hist > 0) & (d.shift(1) > 0) & (d < 0)
        return montar_sinais(compra, venda)


class StochRSIReversao(EstrategiaBase):
    identificador = "stochrsi"
    familia = "momentum"
    descricao = "Cruzamento %K/%D do Stochastic RSI nas zonas extremas."
    stop_atr_padrao, alvo_atr_padrao = 1.5, 2.0

    def gerar_sinais(self, df):
        k, d = ind.stochrsi(df["fechamento"], self.p("periodo"), self.p("k"), self.p("d"))
        return montar_sinais(cruzou_acima(k, d) & (k < self.p("baixo")), cruzou_abaixo(k, d) & (k > self.p("alto")))


def registrar():
    e = []
    for p in [10, 20, 5]:
        e.append(ROCCruzamentoZero(periodo=p))
    for l, c in [(25, 13), (13, 7)]:
        e.append(TSICruzamento(longo=l, curto=c))
    e.append(AwesomeCruzamentoZero(rapido=5, lento=34))
    e.append(AwesomePires(rapido=5, lento=34))
    for p in [14, 9, 21]:
        e.append(RSICruzamento50(periodo=p))
    for r, l, s in [(12, 26, 9), (5, 35, 5)]:
        e.append(MACDHistogramaReversao(rapida=r, lenta=l, sinal=s))
    for p, k, d, b, a in [(14, 3, 3, 20, 80), (14, 3, 3, 30, 70)]:
        e.append(StochRSIReversao(periodo=p, k=k, d=d, baixo=b, alto=a))
    return e
