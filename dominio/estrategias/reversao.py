"""Estratégias de reversão à média / sobrecompra e sobrevenda."""
from __future__ import annotations

from dominio import indicadores as ind
from dominio.estrategias.base import EstrategiaBase, cruzou_acima, cruzou_abaixo, entrou_em, montar_sinais


class RSIReversao(EstrategiaBase):
    identificador = "rsi_reversao"
    familia = "reversao"
    descricao = "Compra quando o RSI sai da zona de sobrevenda; venda quando sai da sobrecompra."
    stop_atr_padrao, alvo_atr_padrao = 1.5, 2.0

    def gerar_sinais(self, df):
        r = ind.rsi(df["fechamento"], self.p("periodo"))
        return montar_sinais(cruzou_acima(r, self.p("sobrevenda")), cruzou_abaixo(r, self.p("sobrecompra")))


class BollingerReversao(EstrategiaBase):
    identificador = "bollinger_reversao"
    familia = "reversao"
    descricao = "Preço volta para dentro das Bandas de Bollinger após extrapolá-las."
    stop_atr_padrao, alvo_atr_padrao = 1.5, 2.0

    def gerar_sinais(self, df):
        _, sup, inf = ind.bollinger(df["fechamento"], self.p("periodo"), self.p("desvio"))
        f = df["fechamento"]
        return montar_sinais(cruzou_acima(f, inf), cruzou_abaixo(f, sup))


class EstocasticoReversao(EstrategiaBase):
    identificador = "estocastico_reversao"
    familia = "reversao"
    descricao = "Cruzamento %K/%D dentro das zonas extremas do Estocástico."
    stop_atr_padrao, alvo_atr_padrao = 1.5, 2.0

    def gerar_sinais(self, df):
        k, d = ind.estocastico(df, self.p("periodo"), self.p("suavizacao"))
        return montar_sinais(cruzou_acima(k, d) & (k < self.p("baixo")), cruzou_abaixo(k, d) & (k > self.p("alto")))


class CCIReversao(EstrategiaBase):
    identificador = "cci_reversao"
    familia = "reversao"
    descricao = "CCI retorna de níveis extremos."
    stop_atr_padrao, alvo_atr_padrao = 1.5, 2.0

    def gerar_sinais(self, df):
        c = ind.cci(df, self.p("periodo"))
        lim = self.p("limiar")
        return montar_sinais(cruzou_acima(c, -lim), cruzou_abaixo(c, lim))


class WilliamsReversao(EstrategiaBase):
    identificador = "williams_reversao"
    familia = "reversao"
    descricao = "Williams %R sai das zonas extremas."
    stop_atr_padrao, alvo_atr_padrao = 1.5, 2.0

    def gerar_sinais(self, df):
        w = ind.williams_r(df, self.p("periodo"))
        return montar_sinais(cruzou_acima(w, self.p("baixo")), cruzou_abaixo(w, self.p("alto")))


class MFIReversao(EstrategiaBase):
    identificador = "mfi_reversao"
    familia = "reversao"
    descricao = "Money Flow Index sai das zonas extremas (usa volume)."
    stop_atr_padrao, alvo_atr_padrao = 1.5, 2.0

    def gerar_sinais(self, df):
        m = ind.mfi(df, self.p("periodo"))
        return montar_sinais(cruzou_acima(m, self.p("baixo")), cruzou_abaixo(m, self.p("alto")))


class ZScoreReversao(EstrategiaBase):
    identificador = "zscore_reversao"
    familia = "reversao"
    descricao = "Preço se afasta N desvios da média e aposta-se no retorno."
    stop_atr_padrao, alvo_atr_padrao = 2.0, 1.5

    def gerar_sinais(self, df):
        z = ind.zscore(df["fechamento"], self.p("periodo"))
        lim = self.p("limiar")
        return montar_sinais(entrou_em(z < -lim), entrou_em(z > lim))


class RSICurtoFiltroTendencia(EstrategiaBase):
    identificador = "rsi_curto_tendencia"
    familia = "reversao"
    descricao = "RSI de período curto em extremo, operando apenas a favor da média longa (pullback)."
    stop_atr_padrao, alvo_atr_padrao = 2.0, 2.0

    def gerar_sinais(self, df):
        r = ind.rsi(df["fechamento"], self.p("periodo_rsi"))
        media = ind.sma(df["fechamento"], self.p("periodo_media"))
        f = df["fechamento"]
        return montar_sinais(entrou_em((f > media) & (r < self.p("sobrevenda"))),
                             entrou_em((f < media) & (r > self.p("sobrecompra"))))


def registrar():
    e = []
    for p, sv, sc in [(14, 30, 70), (7, 20, 80), (21, 35, 65), (2, 10, 90)]:
        e.append(RSIReversao(periodo=p, sobrevenda=sv, sobrecompra=sc))
    for p, d in [(20, 2.0), (20, 2.5), (10, 1.5)]:
        e.append(BollingerReversao(periodo=p, desvio=d))
    for p, s, b, a in [(14, 3, 20, 80), (5, 3, 20, 80), (21, 5, 25, 75)]:
        e.append(EstocasticoReversao(periodo=p, suavizacao=s, baixo=b, alto=a))
    for p, lim in [(20, 100), (14, 150), (30, 200)]:
        e.append(CCIReversao(periodo=p, limiar=lim))
    for p, b, a in [(14, -80, -20), (10, -90, -10)]:
        e.append(WilliamsReversao(periodo=p, baixo=b, alto=a))
    for p, b, a in [(14, 20, 80), (10, 25, 75)]:
        e.append(MFIReversao(periodo=p, baixo=b, alto=a))
    for p, lim in [(20, 2.0), (50, 2.5), (30, 1.5)]:
        e.append(ZScoreReversao(periodo=p, limiar=lim))
    for pr, sv, sc, pm in [(2, 10, 90, 200), (3, 15, 85, 100), (4, 20, 80, 50)]:
        e.append(RSICurtoFiltroTendencia(periodo_rsi=pr, sobrevenda=sv, sobrecompra=sc, periodo_media=pm))
    return e
