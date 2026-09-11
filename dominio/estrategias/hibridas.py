"""Estratégias híbridas que combinam mais de um indicador."""
from __future__ import annotations

import pandas as pd

from dominio import indicadores as ind
from dominio.estrategias.base import EstrategiaBase, cruzou_acima, cruzou_abaixo, entrou_em, montar_sinais


class RSIBollinger(EstrategiaBase):
    identificador = "rsi_bollinger"
    familia = "hibrida"
    descricao = "Preço fora das Bandas de Bollinger com RSI em extremo: reversão."
    stop_atr_padrao, alvo_atr_padrao = 1.5, 2.0

    def gerar_sinais(self, df):
        _, sup, inf = ind.bollinger(df["fechamento"], self.p("periodo_bb"), self.p("desvio"))
        r = ind.rsi(df["fechamento"], self.p("periodo_rsi"))
        f = df["fechamento"]
        return montar_sinais(entrou_em((f < inf) & (r < 30)), entrou_em((f > sup) & (r > 70)))


class MACDComADX(EstrategiaBase):
    identificador = "macd_adx"
    familia = "hibrida"
    descricao = "Cruzamento do MACD apenas quando o ADX indica tendência."
    stop_atr_padrao, alvo_atr_padrao = 2.0, 3.0

    def gerar_sinais(self, df):
        linha, sinal, _ = ind.macd(df["fechamento"])
        adx, _, _ = ind.adx(df, self.p("periodo_adx"))
        forte = adx > self.p("limiar")
        return montar_sinais(cruzou_acima(linha, sinal) & forte, cruzou_abaixo(linha, sinal) & forte)


class PullbackEMA(EstrategiaBase):
    identificador = "pullback_ema"
    familia = "hibrida"
    descricao = "Tendência pela EMA longa; entrada quando o RSI recupera de um recuo."
    stop_atr_padrao, alvo_atr_padrao = 1.5, 3.0

    def gerar_sinais(self, df):
        e = ind.ema(df["fechamento"], self.p("periodo_ema"))
        r = ind.rsi(df["fechamento"], self.p("periodo_rsi"))
        f = df["fechamento"]
        return montar_sinais((f > e) & cruzou_acima(r, 40), (f < e) & cruzou_abaixo(r, 60))


class VotacaoIndicadores(EstrategiaBase):
    identificador = "votacao"
    familia = "hibrida"
    descricao = "Cinco indicadores votam (EMA 20/50, RSI, MACD, VWAP, DI): entra quando há consenso."
    stop_atr_padrao, alvo_atr_padrao = 2.0, 3.0

    def gerar_sinais(self, df):
        f = df["fechamento"]
        votos = pd.DataFrame(index=df.index)
        votos["ema"] = (ind.ema(f, 20) > ind.ema(f, 50)).astype(int) * 2 - 1
        votos["rsi"] = (ind.rsi(f, 14) > 50).astype(int) * 2 - 1
        votos["macd"] = (ind.macd(f)[2] > 0).astype(int) * 2 - 1
        votos["vwap"] = (f > ind.vwap(df)).astype(int) * 2 - 1
        _, dip, dim = ind.adx(df, 14)
        votos["di"] = (dip > dim).astype(int) * 2 - 1
        soma = votos.sum(axis=1)
        m = self.p("minimo_votos")
        return montar_sinais(entrou_em(soma >= m), entrou_em(soma <= -m))


class SupertrendComRSI(EstrategiaBase):
    identificador = "supertrend_rsi"
    familia = "hibrida"
    descricao = "Direção do Supertrend com gatilho de RSI cruzando 50."
    stop_atr_padrao, alvo_atr_padrao = 2.0, 3.0

    def gerar_sinais(self, df):
        _, direcao = ind.supertrend(df, self.p("periodo"), self.p("mult"))
        r = ind.rsi(df["fechamento"], self.p("periodo_rsi"))
        return montar_sinais((direcao == 1) & cruzou_acima(r, 50), (direcao == -1) & cruzou_abaixo(r, 50))


class VWAPMomentum(EstrategiaBase):
    identificador = "vwap_momentum"
    familia = "hibrida"
    descricao = "Preço do lado da VWAP e ROC cruzando zero na mesma direção."
    stop_atr_padrao, alvo_atr_padrao = 1.5, 3.0

    def gerar_sinais(self, df):
        f = df["fechamento"]
        v = ind.vwap(df)
        r = ind.roc(f, self.p("periodo_roc"))
        return montar_sinais((f > v) & cruzou_acima(r, 0), (f < v) & cruzou_abaixo(r, 0))


def registrar():
    e = []
    for pr, pb, d in [(14, 20, 2.0), (7, 20, 2.5)]:
        e.append(RSIBollinger(periodo_rsi=pr, periodo_bb=pb, desvio=d))
    e.append(MACDComADX(periodo_adx=14, limiar=25))
    for pe, pr in [(50, 14), (100, 7)]:
        e.append(PullbackEMA(periodo_ema=pe, periodo_rsi=pr))
    for m in [4, 5]:
        e.append(VotacaoIndicadores(minimo_votos=m))
    e.append(SupertrendComRSI(periodo=10, mult=3.0, periodo_rsi=14))
    e.append(VWAPMomentum(periodo_roc=10))
    return e
