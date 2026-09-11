"""Estratégias baseadas em padrões de candles (price action)."""
from __future__ import annotations

from dominio import indicadores as ind
from dominio.estrategias.base import EstrategiaBase, montar_sinais


def _partes(df):
    corpo = (df["fechamento"] - df["abertura"]).abs()
    amplitude = (df["maxima"] - df["minima"]).replace(0, float("nan"))
    sombra_sup = df["maxima"] - df[["abertura", "fechamento"]].max(axis=1)
    sombra_inf = df[["abertura", "fechamento"]].min(axis=1) - df["minima"]
    return corpo, amplitude, sombra_sup, sombra_inf


class EngolfoComTendencia(EstrategiaBase):
    identificador = "engolfo"
    familia = "padroes_candle"
    descricao = "Engolfo de alta/baixa a favor da EMA de referência."
    stop_atr_padrao, alvo_atr_padrao = 1.5, 2.5

    def gerar_sinais(self, df):
        a, f = df["abertura"], df["fechamento"]
        e = ind.ema(f, self.p("periodo_media"))
        alta = (f.shift(1) < a.shift(1)) & (f > a) & (a <= f.shift(1)) & (f >= a.shift(1)) & (f > e)
        baixa = (f.shift(1) > a.shift(1)) & (f < a) & (a >= f.shift(1)) & (f <= a.shift(1)) & (f < e)
        return montar_sinais(alta, baixa)


class MarteloEstrela(EstrategiaBase):
    identificador = "martelo_estrela"
    familia = "padroes_candle"
    descricao = "Martelo em queda (abaixo da EMA) e estrela cadente em alta (acima da EMA): reversão."
    stop_atr_padrao, alvo_atr_padrao = 1.5, 2.5

    def gerar_sinais(self, df):
        corpo, amp, ss, si = _partes(df)
        e = ind.ema(df["fechamento"], self.p("periodo_media"))
        f = df["fechamento"]
        martelo = (si >= 2 * corpo) & (ss <= 0.3 * corpo + 1e-9) & (f < e)
        estrela = (ss >= 2 * corpo) & (si <= 0.3 * corpo + 1e-9) & (f > e)
        return montar_sinais(martelo, estrela)


class DojiComRSI(EstrategiaBase):
    identificador = "doji_rsi"
    familia = "padroes_candle"
    descricao = "Doji em zona extrema do RSI: reversão."
    stop_atr_padrao, alvo_atr_padrao = 1.5, 2.0

    def gerar_sinais(self, df):
        corpo, amp, _, _ = _partes(df)
        doji = corpo <= 0.1 * amp
        r = ind.rsi(df["fechamento"], self.p("periodo_rsi"))
        return montar_sinais(doji & (r < 30), doji & (r > 70))


class TresSoldadosCorvos(EstrategiaBase):
    identificador = "tres_soldados"
    familia = "padroes_candle"
    descricao = "Três candles consecutivos de alta (soldados) ou de baixa (corvos) com fechamentos progressivos."
    stop_atr_padrao, alvo_atr_padrao = 2.0, 3.0

    def gerar_sinais(self, df):
        a, f = df["abertura"], df["fechamento"]
        alta = f > a
        baixa = f < a
        soldados = alta & alta.shift(1) & alta.shift(2) & (f > f.shift(1)) & (f.shift(1) > f.shift(2))
        corvos = baixa & baixa.shift(1) & baixa.shift(2) & (f < f.shift(1)) & (f.shift(1) < f.shift(2))
        return montar_sinais(soldados.fillna(False), corvos.fillna(False))


class InsideBarRompimento(EstrategiaBase):
    identificador = "inside_bar"
    familia = "padroes_candle"
    descricao = "Rompimento da máxima/mínima de um inside bar."
    stop_atr_padrao, alvo_atr_padrao = 1.0, 2.0

    def gerar_sinais(self, df):
        alta, baixa, f = df["maxima"], df["minima"], df["fechamento"]
        inside = (alta.shift(1) < alta.shift(2)) & (baixa.shift(1) > baixa.shift(2))
        return montar_sinais(inside & (f > alta.shift(1)), inside & (f < baixa.shift(1)))


class PinBarContinuacao(EstrategiaBase):
    identificador = "pin_bar"
    familia = "padroes_candle"
    descricao = "Pin bar de rejeição a favor da tendência (acima/abaixo da EMA)."
    stop_atr_padrao, alvo_atr_padrao = 1.0, 2.5

    def gerar_sinais(self, df):
        corpo, amp, ss, si = _partes(df)
        e = ind.ema(df["fechamento"], self.p("periodo_media"))
        f = df["fechamento"]
        pin_alta = (si >= 0.66 * amp) & (f > e)
        pin_baixa = (ss >= 0.66 * amp) & (f < e)
        return montar_sinais(pin_alta, pin_baixa)


def registrar():
    e = []
    for p in [20, 50]:
        e.append(EngolfoComTendencia(periodo_media=p))
    for p in [20, 50]:
        e.append(MarteloEstrela(periodo_media=p))
    e.append(DojiComRSI(periodo_rsi=14))
    e.append(TresSoldadosCorvos())
    e.append(InsideBarRompimento())
    e.append(PinBarContinuacao(periodo_media=20))
    return e
