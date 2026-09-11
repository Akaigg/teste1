"""Estratégias seguidoras de tendência."""
from __future__ import annotations

import pandas as pd

from dominio import indicadores as ind
from dominio.estrategias.base import EstrategiaBase, cruzou_acima, cruzou_abaixo, entrou_em, montar_sinais


class CruzamentoMedias(EstrategiaBase):
    identificador = "cruzamento_medias"
    familia = "tendencia"
    descricao = "Compra quando a EMA rápida cruza acima da lenta; venda no cruzamento inverso."
    stop_atr_padrao, alvo_atr_padrao = 2.0, 3.0

    def gerar_sinais(self, df):
        rapida = ind.ema(df["fechamento"], self.p("rapida"))
        lenta = ind.ema(df["fechamento"], self.p("lenta"))
        return montar_sinais(cruzou_acima(rapida, lenta), cruzou_abaixo(rapida, lenta))


class AlinhamentoTresMedias(EstrategiaBase):
    identificador = "tres_medias"
    familia = "tendencia"
    descricao = "Entra quando três EMAs ficam alinhadas (curta > média > longa ou o inverso)."
    stop_atr_padrao, alvo_atr_padrao = 2.0, 3.0

    def gerar_sinais(self, df):
        c = ind.ema(df["fechamento"], self.p("curta"))
        m = ind.ema(df["fechamento"], self.p("media"))
        l = ind.ema(df["fechamento"], self.p("longa"))
        return montar_sinais(entrou_em((c > m) & (m > l)), entrou_em((c < m) & (m < l)))


class MACDCruzamento(EstrategiaBase):
    identificador = "macd_cruzamento"
    familia = "tendencia"
    descricao = "Cruzamento da linha MACD com sua linha de sinal."
    stop_atr_padrao, alvo_atr_padrao = 2.0, 3.0

    def gerar_sinais(self, df):
        linha, sinal, _ = ind.macd(df["fechamento"], self.p("rapida"), self.p("lenta"), self.p("sinal"))
        return montar_sinais(cruzou_acima(linha, sinal), cruzou_abaixo(linha, sinal))


class ADXDirecional(EstrategiaBase):
    identificador = "adx_direcional"
    familia = "tendencia"
    descricao = "Cruzamento de DI+ e DI- confirmado por ADX acima do limiar (tendência forte)."
    stop_atr_padrao, alvo_atr_padrao = 2.0, 3.0

    def gerar_sinais(self, df):
        adx, di_mais, di_menos = ind.adx(df, self.p("periodo"))
        forte = adx > self.p("limiar")
        return montar_sinais(cruzou_acima(di_mais, di_menos) & forte, cruzou_abaixo(di_mais, di_menos) & forte)


class SupertrendTendencia(EstrategiaBase):
    identificador = "supertrend"
    familia = "tendencia"
    descricao = "Entra na virada de direção do Supertrend."
    stop_atr_padrao, alvo_atr_padrao = 2.0, 4.0

    def gerar_sinais(self, df):
        _, direcao = ind.supertrend(df, self.p("periodo"), self.p("mult"))
        return montar_sinais(entrou_em(direcao == 1), entrou_em(direcao == -1))


class HullTendencia(EstrategiaBase):
    identificador = "hull"
    familia = "tendencia"
    descricao = "Virada de inclinação da Hull Moving Average."
    stop_atr_padrao, alvo_atr_padrao = 1.5, 3.0

    def gerar_sinais(self, df):
        h = ind.hull(df["fechamento"], self.p("periodo"))
        subindo = h > h.shift(1)
        return montar_sinais(entrou_em(subindo), entrou_em(~subindo & h.notna()))


class IchimokuCruzamento(EstrategiaBase):
    identificador = "ichimoku"
    familia = "tendencia"
    descricao = "Cruzamento Tenkan/Kijun com preço do mesmo lado da nuvem."
    stop_atr_padrao, alvo_atr_padrao = 2.0, 4.0

    def gerar_sinais(self, df):
        tenkan, kijun, span_a, span_b = ind.ichimoku(df, self.p("tenkan"), self.p("kijun"), self.p("senkou"))
        topo = pd.concat([span_a, span_b], axis=1).max(axis=1)
        base = pd.concat([span_a, span_b], axis=1).min(axis=1)
        f = df["fechamento"]
        return montar_sinais(cruzou_acima(tenkan, kijun) & (f > topo), cruzou_abaixo(tenkan, kijun) & (f < base))


class SARParabolico(EstrategiaBase):
    identificador = "sar_parabolico"
    familia = "tendencia"
    descricao = "Preço cruza o SAR Parabólico (virada de tendência)."
    stop_atr_padrao, alvo_atr_padrao = 2.0, 3.0

    def gerar_sinais(self, df):
        sar = ind.psar(df, self.p("passo"), self.p("maximo"))
        f = df["fechamento"]
        return montar_sinais(cruzou_acima(f, sar), cruzou_abaixo(f, sar))


class PrecoCruzaMedia(EstrategiaBase):
    identificador = "preco_cruza_media"
    familia = "tendencia"
    descricao = "Fechamento cruza a média móvel simples."
    stop_atr_padrao, alvo_atr_padrao = 1.5, 2.5

    def gerar_sinais(self, df):
        media = ind.sma(df["fechamento"], self.p("periodo"))
        return montar_sinais(cruzou_acima(df["fechamento"], media), cruzou_abaixo(df["fechamento"], media))


def registrar():
    e = []
    for r, l in [(9, 21), (12, 26), (20, 50), (50, 200), (5, 13)]:
        e.append(CruzamentoMedias(rapida=r, lenta=l))
    for c, m, l in [(8, 21, 55), (5, 20, 60), (10, 30, 100)]:
        e.append(AlinhamentoTresMedias(curta=c, media=m, longa=l))
    for r, l, s in [(12, 26, 9), (8, 17, 9), (19, 39, 9)]:
        e.append(MACDCruzamento(rapida=r, lenta=l, sinal=s))
    for p, lim in [(14, 20), (14, 25), (20, 30)]:
        e.append(ADXDirecional(periodo=p, limiar=lim))
    for p, m in [(10, 3.0), (7, 2.0), (14, 2.5)]:
        e.append(SupertrendTendencia(periodo=p, mult=m))
    for p in [9, 16, 25]:
        e.append(HullTendencia(periodo=p))
    for t, k, s in [(9, 26, 52), (7, 22, 44)]:
        e.append(IchimokuCruzamento(tenkan=t, kijun=k, senkou=s))
    for passo, maximo in [(0.02, 0.2), (0.01, 0.1), (0.03, 0.3)]:
        e.append(SARParabolico(passo=passo, maximo=maximo))
    for p in [20, 50, 100]:
        e.append(PrecoCruzaMedia(periodo=p))
    return e
