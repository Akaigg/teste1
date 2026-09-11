"""Estratégias que usam volume e VWAP."""
from __future__ import annotations

from dominio import indicadores as ind
from dominio.estrategias.base import EstrategiaBase, cruzou_acima, cruzou_abaixo, entrou_em, montar_sinais


class OBVCruzamentoMedia(EstrategiaBase):
    identificador = "obv_media"
    familia = "volume"
    descricao = "On Balance Volume cruza sua média móvel."
    stop_atr_padrao, alvo_atr_padrao = 2.0, 3.0

    def gerar_sinais(self, df):
        o = ind.obv(df)
        m = ind.sma(o, self.p("periodo"))
        return montar_sinais(cruzou_acima(o, m), cruzou_abaixo(o, m))


class VWAPReversao(EstrategiaBase):
    identificador = "vwap_reversao"
    familia = "volume"
    descricao = "Preço cruza de volta a VWAP após N barras do lado oposto."
    stop_atr_padrao, alvo_atr_padrao = 1.5, 2.0

    def gerar_sinais(self, df):
        v = ind.vwap(df)
        f = df["fechamento"]
        n = self.p("confirmacao")
        abaixo = (f < v).rolling(n).sum().shift(1) >= n
        acima = (f > v).rolling(n).sum().shift(1) >= n
        return montar_sinais(cruzou_acima(f, v) & abaixo, cruzou_abaixo(f, v) & acima)


class VWAPTendenciaPullback(EstrategiaBase):
    identificador = "vwap_pullback"
    familia = "volume"
    descricao = "Preço acima da VWAP com EMA subindo: compra quando a mínima toca a VWAP (e o inverso)."
    stop_atr_padrao, alvo_atr_padrao = 1.5, 3.0

    def gerar_sinais(self, df):
        v = ind.vwap(df)
        e = ind.ema(df["fechamento"], self.p("periodo_ema"))
        f = df["fechamento"]
        compra = (f > v) & (e > e.shift(1)) & (df["minima"] <= v)
        venda = (f < v) & (e < e.shift(1)) & (df["maxima"] >= v)
        return montar_sinais(entrou_em(compra), entrou_em(venda))


class VolumeClimax(EstrategiaBase):
    identificador = "volume_climax"
    familia = "volume"
    descricao = "Volume muito acima da média: segue a direção do candle."
    stop_atr_padrao, alvo_atr_padrao = 1.5, 2.5

    def gerar_sinais(self, df):
        forte = df["volume"] > self.p("mult") * ind.sma(df["volume"], self.p("periodo"))
        alta = df["fechamento"] > df["abertura"]
        return montar_sinais(forte & alta, forte & ~alta)


class ForceIndexCruzamento(EstrategiaBase):
    identificador = "force_index"
    familia = "volume"
    descricao = "Force Index cruza a linha zero."
    stop_atr_padrao, alvo_atr_padrao = 2.0, 3.0

    def gerar_sinais(self, df):
        fi = ind.force_index(df, self.p("periodo"))
        return montar_sinais(cruzou_acima(fi, 0), cruzou_abaixo(fi, 0))


class CMFReversao(EstrategiaBase):
    identificador = "cmf"
    familia = "volume"
    descricao = "Chaikin Money Flow cruza os limiares de pressão compradora/vendedora."
    stop_atr_padrao, alvo_atr_padrao = 2.0, 3.0

    def gerar_sinais(self, df):
        c = ind.cmf(df, self.p("periodo"))
        lim = self.p("limiar")
        return montar_sinais(cruzou_acima(c, lim), cruzou_abaixo(c, -lim))


def registrar():
    e = []
    for p in [20, 50]:
        e.append(OBVCruzamentoMedia(periodo=p))
    for n in [1, 3]:
        e.append(VWAPReversao(confirmacao=n))
    e.append(VWAPTendenciaPullback(periodo_ema=20))
    for p, m in [(20, 2.0), (20, 3.0)]:
        e.append(VolumeClimax(periodo=p, mult=m))
    for p in [13, 2]:
        e.append(ForceIndexCruzamento(periodo=p))
    for p, lim in [(20, 0.1), (10, 0.15)]:
        e.append(CMFReversao(periodo=p, limiar=lim))
    return e
