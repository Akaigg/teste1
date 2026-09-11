"""Estratégias baseadas em expansão/contração de volatilidade."""
from __future__ import annotations

from dominio import indicadores as ind
from dominio.estrategias.base import EstrategiaBase, entrou_em, montar_sinais


class ExpansaoVolatilidade(EstrategiaBase):
    identificador = "expansao_volatilidade"
    familia = "volatilidade"
    descricao = "Candle com amplitude muito acima do ATR: segue a direção do candle."
    stop_atr_padrao, alvo_atr_padrao = 1.5, 3.0

    def gerar_sinais(self, df):
        amplitude = df["maxima"] - df["minima"]
        referencia = ind.atr(df, self.p("periodo")).shift(1) * self.p("mult")
        grande = amplitude > referencia
        alta = df["fechamento"] > df["abertura"]
        return montar_sinais(grande & alta, grande & ~alta)


class ContracaoNR(EstrategiaBase):
    identificador = "contracao_nr"
    familia = "volatilidade"
    descricao = "Barra mais estreita das últimas N (NR-N) seguida de rompimento de sua máxima/mínima."
    stop_atr_padrao, alvo_atr_padrao = 1.0, 2.5

    def gerar_sinais(self, df):
        amplitude = df["maxima"] - df["minima"]
        estreita = (amplitude == amplitude.rolling(self.p("periodo")).min()).shift(1, fill_value=False)
        f = df["fechamento"]
        return montar_sinais(estreita & (f > df["maxima"].shift(1)), estreita & (f < df["minima"].shift(1)))


class CanalATR(EstrategiaBase):
    identificador = "canal_atr"
    familia = "volatilidade"
    descricao = "Fechamento avança mais de k ATRs em relação ao fechamento anterior."
    stop_atr_padrao, alvo_atr_padrao = 1.5, 2.5

    def gerar_sinais(self, df):
        a = ind.atr(df, self.p("periodo")).shift(1) * self.p("mult")
        variacao = df["fechamento"] - df["fechamento"].shift(1)
        return montar_sinais(entrou_em(variacao > a), entrou_em(variacao < -a))


def registrar():
    e = []
    for p, m in [(14, 1.5), (14, 2.0), (20, 2.5)]:
        e.append(ExpansaoVolatilidade(periodo=p, mult=m))
    for p in [7, 4]:
        e.append(ContracaoNR(periodo=p))
    for p, m in [(14, 1.0), (14, 1.5), (10, 2.0)]:
        e.append(CanalATR(periodo=p, mult=m))
    return e
