"""
Estratégias ESTATÍSTICAS: usam propriedades mensuráveis da série (z-scores em
vários horizontes, autocorrelação dos retornos, regressão linear móvel com R²
e desvio residual) em vez de um único indicador de gráfico.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from dominio import indicadores as ind
from dominio.estrategias.base import EstrategiaBase, entrou_em, limitar, montar_sinais, normalizar


class ZScoreMultiplo(EstrategiaBase):
    identificador = "zscore_multiplo"
    familia = "estatistica"
    descricao = ("Z-score combinado em 3 horizontes (10, 20 e 40 barras, pesos 0.5/1/0.5) que só opera reversão quando a "
                 "autocorrelação recente dos retornos indica mercado revertendo à média, o ATR não está em pânico e o "
                 "z-score começa a voltar (virada) após extrapolar o limiar.")
    stop_atr_padrao, alvo_atr_padrao = 2.0, 1.5

    def _z_combinado(self, df):
        f = df["fechamento"]
        zs = {k: ind.zscore(f, k) for k in (10, 20, 40)}
        return (0.5 * zs[10] + 1.0 * zs[20] + 0.5 * zs[40]) / 2.0

    def vies(self, df):
        return normalizar(-self._z_combinado(df), 2.0)

    def gerar_sinais(self, df):
        f = df["fechamento"]
        z = self._z_combinado(df)
        lim = self.p("limiar")
        retornos = f.pct_change()
        ac = ind.autocorrelacao(retornos, self.p("periodo_ac"), 1)
        revertendo = ac <= self.p("autocorr_max")
        calmo = ind.percentil(ind.atr(df, 14), 200) <= 0.90
        compras = entrou_em((z.shift(1) <= -lim) & (z > z.shift(1)) & (f > f.shift(1)) & revertendo & calmo)
        vendas = entrou_em((z.shift(1) >= lim) & (z < z.shift(1)) & (f < f.shift(1)) & revertendo & calmo)
        return montar_sinais(compras, vendas)


class CanalRegressao(EstrategiaBase):
    identificador = "canal_regressao"
    familia = "estatistica"
    descricao = ("Regressão linear móvel do fechamento: exige R² mínimo e inclinação relevante (≥1 ATR ao longo da janela). "
                 "Compra no toque da banda inferior do canal (ajuste - k·desvio residual) com fechamento de volta acima, "
                 "a favor da inclinação; venda simétrica. Rejeita canais horizontais ou pouco explicativos.")
    stop_atr_padrao, alvo_atr_padrao = 1.5, 3.0

    def _canal(self, df):
        f = df["fechamento"]
        incl, r2, ajuste, resid = ind.regressao_linear(f, self.p("periodo"))
        return incl, r2, ajuste, resid

    def vies(self, df):
        incl, r2, _, _ = self._canal(df)
        a = ind.atr(df, 14)
        return normalizar(incl * self.p("periodo") / a, 2.0) * r2

    def gerar_sinais(self, df):
        f, mn, mx, ab = df["fechamento"], df["minima"], df["maxima"], df["abertura"]
        a = ind.atr(df, 14)
        p = self.p("periodo")
        incl, r2, ajuste, resid = self._canal(df)
        k = self.p("desvios")
        inferior, superior = ajuste - k * resid, ajuste + k * resid
        explicativo = r2 >= self.p("r2_min")
        amplitude = (incl * p / a).abs() >= 1.0
        alta = explicativo & amplitude & (incl > 0)
        baixa = explicativo & amplitude & (incl < 0)
        compras = entrou_em(alta & (mn <= inferior) & (f > inferior) & (f > ab))
        vendas = entrou_em(baixa & (mx >= superior) & (f < superior) & (f < ab))
        return montar_sinais(compras, vendas)


class MomentumPersistente(EstrategiaBase):
    identificador = "momentum_persistente"
    familia = "estatistica"
    descricao = ("Continuação apenas quando os retornos mostram persistência (autocorrelação positiva) e o caminho do preço é "
                 "eficiente (Efficiency Ratio alto). Gatilho: ROC multi-horizonte normalizado pela volatilidade acima do "
                 "limiar e rompimento da máxima/mínima das últimas N barras.")
    stop_atr_padrao, alvo_atr_padrao = 2.0, 4.0

    def _momentum(self, df):
        f = df["fechamento"]
        vol_rel = ind.atr(df, 14) / f * 100
        rocs = [normalizar(ind.roc(f, k) / (vol_rel * np.sqrt(k)), 1.0) for k in (5, 10, 20)]
        return pd.concat(rocs, axis=1).mean(axis=1, skipna=False)

    def vies(self, df):
        return self._momentum(df)

    def gerar_sinais(self, df):
        f = df["fechamento"]
        retornos = f.pct_change()
        ac = ind.autocorrelacao(retornos, self.p("periodo_ac"), 1)
        persistente = ac >= self.p("autocorr_min")
        eficiente = ind.eficiencia_kaufman(f, 10) >= self.p("eficiencia_min")
        mom = self._momentum(df)
        sup, inf, _ = ind.donchian(df, self.p("rompimento"))
        lim = self.p("limiar")
        compras = entrou_em(persistente & eficiente & (mom >= lim) & (f > sup))
        vendas = entrou_em(persistente & eficiente & (mom <= -lim) & (f < inf))
        return montar_sinais(compras, vendas)


def registrar():
    e = []
    for lim, pac, acm in [(2.0, 100, 0.05), (2.2, 60, 0.05), (1.8, 150, 0.10)]:
        e.append(ZScoreMultiplo(limiar=lim, periodo_ac=pac, autocorr_max=acm))
    for p, r2, k in [(50, 0.60, 1.5), (100, 0.70, 2.0), (30, 0.50, 1.5), (80, 0.65, 1.0)]:
        e.append(CanalRegressao(periodo=p, r2_min=r2, desvios=k))
    for pac, acmin, ef, rp, lim in [(60, 0.05, 0.35, 10, 0.30), (100, 0.10, 0.40, 20, 0.35), (40, 0.0, 0.30, 10, 0.25)]:
        e.append(MomentumPersistente(periodo_ac=pac, autocorr_min=acmin, eficiencia_min=ef, rompimento=rp, limiar=lim))
    return e
