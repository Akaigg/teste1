"""
Indicadores técnicos como funções puras sobre pandas.

Convenção do DataFrame de candles: índice DatetimeIndex e colunas
'abertura', 'maxima', 'minima', 'fechamento', 'volume'.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


# ----------------------------------------------------------------- médias
def sma(serie: pd.Series, periodo: int) -> pd.Series:
    return serie.rolling(periodo).mean()


def ema(serie: pd.Series, periodo: int) -> pd.Series:
    return serie.ewm(span=periodo, adjust=False).mean()


def wma(serie: pd.Series, periodo: int) -> pd.Series:
    pesos = np.arange(1, periodo + 1, dtype=float)
    return serie.rolling(periodo).apply(lambda x: np.dot(x, pesos) / pesos.sum(), raw=True)


def hull(serie: pd.Series, periodo: int) -> pd.Series:
    metade = max(2, periodo // 2)
    raiz = max(2, int(round(np.sqrt(periodo))))
    return wma(2 * wma(serie, metade) - wma(serie, periodo), raiz)


# ------------------------------------------------------------ volatilidade
def true_range(df: pd.DataFrame) -> pd.Series:
    fech_ant = df["fechamento"].shift(1)
    return pd.concat([
        df["maxima"] - df["minima"],
        (df["maxima"] - fech_ant).abs(),
        (df["minima"] - fech_ant).abs(),
    ], axis=1).max(axis=1)


def atr(df: pd.DataFrame, periodo: int = 14) -> pd.Series:
    return true_range(df).ewm(alpha=1 / periodo, adjust=False, min_periods=periodo).mean()


def bollinger(serie: pd.Series, periodo: int = 20, desvio: float = 2.0):
    media = sma(serie, periodo)
    dp = serie.rolling(periodo).std(ddof=0)
    return media, media + desvio * dp, media - desvio * dp


def keltner(df: pd.DataFrame, periodo: int = 20, mult: float = 1.5):
    meio = ema(df["fechamento"], periodo)
    faixa = atr(df, periodo) * mult
    return meio, meio + faixa, meio - faixa


def donchian(df: pd.DataFrame, periodo: int):
    """Canal calculado apenas com barras anteriores (sem incluir a atual)."""
    sup = df["maxima"].shift(1).rolling(periodo).max()
    inf = df["minima"].shift(1).rolling(periodo).min()
    return sup, inf, (sup + inf) / 2


def zscore(serie: pd.Series, periodo: int) -> pd.Series:
    media = sma(serie, periodo)
    dp = serie.rolling(periodo).std(ddof=0)
    return (serie - media) / dp.replace(0, np.nan)


# ---------------------------------------------------------------- osciladores
def rsi(serie: pd.Series, periodo: int = 14) -> pd.Series:
    delta = serie.diff()
    ganho = delta.clip(lower=0)
    perda = -delta.clip(upper=0)
    mg = ganho.ewm(alpha=1 / periodo, adjust=False, min_periods=periodo).mean()
    mp = perda.ewm(alpha=1 / periodo, adjust=False, min_periods=periodo).mean()
    rs = mg / (mp + 1e-10)
    return 100 - 100 / (1 + rs)


def macd(serie: pd.Series, rapida: int = 12, lenta: int = 26, sinal: int = 9):
    linha = ema(serie, rapida) - ema(serie, lenta)
    linha_sinal = ema(linha, sinal)
    return linha, linha_sinal, linha - linha_sinal


def estocastico(df: pd.DataFrame, periodo: int = 14, suavizacao: int = 3):
    minimo = df["minima"].rolling(periodo).min()
    maximo = df["maxima"].rolling(periodo).max()
    k_bruto = 100 * (df["fechamento"] - minimo) / (maximo - minimo).replace(0, np.nan)
    k = sma(k_bruto, suavizacao)
    d = sma(k, 3)
    return k, d


def stochrsi(serie: pd.Series, periodo: int = 14, suav_k: int = 3, suav_d: int = 3):
    r = rsi(serie, periodo)
    minimo = r.rolling(periodo).min()
    maximo = r.rolling(periodo).max()
    k = sma(100 * (r - minimo) / (maximo - minimo).replace(0, np.nan), suav_k)
    return k, sma(k, suav_d)


def cci(df: pd.DataFrame, periodo: int = 20) -> pd.Series:
    tp = (df["maxima"] + df["minima"] + df["fechamento"]) / 3
    media = sma(tp, periodo)
    desvio_medio = tp.rolling(periodo).apply(lambda x: np.mean(np.abs(x - x.mean())), raw=True)
    return (tp - media) / (0.015 * desvio_medio.replace(0, np.nan))


def williams_r(df: pd.DataFrame, periodo: int = 14) -> pd.Series:
    maximo = df["maxima"].rolling(periodo).max()
    minimo = df["minima"].rolling(periodo).min()
    return -100 * (maximo - df["fechamento"]) / (maximo - minimo).replace(0, np.nan)


def roc(serie: pd.Series, periodo: int) -> pd.Series:
    return 100 * (serie / serie.shift(periodo) - 1)


def tsi(serie: pd.Series, longo: int = 25, curto: int = 13) -> pd.Series:
    variacao = serie.diff()
    num = ema(ema(variacao, longo), curto)
    den = ema(ema(variacao.abs(), longo), curto)
    return 100 * num / den.replace(0, np.nan)


def awesome(df: pd.DataFrame, rapido: int = 5, lento: int = 34) -> pd.Series:
    hl2 = (df["maxima"] + df["minima"]) / 2
    return sma(hl2, rapido) - sma(hl2, lento)


def adx(df: pd.DataFrame, periodo: int = 14):
    alta = df["maxima"].diff()
    baixa = -df["minima"].diff()
    dm_mais = pd.Series(np.where((alta > baixa) & (alta > 0), alta, 0.0), index=df.index)
    dm_menos = pd.Series(np.where((baixa > alta) & (baixa > 0), baixa, 0.0), index=df.index)
    tr_suave = true_range(df).ewm(alpha=1 / periodo, adjust=False).mean()
    di_mais = 100 * dm_mais.ewm(alpha=1 / periodo, adjust=False).mean() / tr_suave.replace(0, np.nan)
    di_menos = 100 * dm_menos.ewm(alpha=1 / periodo, adjust=False).mean() / tr_suave.replace(0, np.nan)
    dx = 100 * (di_mais - di_menos).abs() / (di_mais + di_menos).replace(0, np.nan)
    return dx.ewm(alpha=1 / periodo, adjust=False).mean(), di_mais, di_menos


# ---------------------------------------------------------------- volume
def obv(df: pd.DataFrame) -> pd.Series:
    return (np.sign(df["fechamento"].diff()).fillna(0) * df["volume"]).cumsum()


def vwap(df: pd.DataFrame) -> pd.Series:
    """VWAP com reinício diário."""
    dia = df.index.normalize()
    tp = (df["maxima"] + df["minima"] + df["fechamento"]) / 3
    pv = (tp * df["volume"]).groupby(dia).cumsum()
    v = df["volume"].groupby(dia).cumsum()
    return pv / v.replace(0, np.nan)


def mfi(df: pd.DataFrame, periodo: int = 14) -> pd.Series:
    tp = (df["maxima"] + df["minima"] + df["fechamento"]) / 3
    fluxo = tp * df["volume"]
    positivo = fluxo.where(tp > tp.shift(1), 0.0).rolling(periodo).sum()
    negativo = fluxo.where(tp < tp.shift(1), 0.0).rolling(periodo).sum()
    return 100 - 100 / (1 + positivo / negativo.replace(0, np.nan))


def cmf(df: pd.DataFrame, periodo: int = 20) -> pd.Series:
    faixa = (df["maxima"] - df["minima"]).replace(0, np.nan)
    mult = ((df["fechamento"] - df["minima"]) - (df["maxima"] - df["fechamento"])) / faixa
    return (mult * df["volume"]).rolling(periodo).sum() / df["volume"].rolling(periodo).sum().replace(0, np.nan)


def force_index(df: pd.DataFrame, periodo: int = 13) -> pd.Series:
    return ema(df["fechamento"].diff() * df["volume"], periodo)


# ------------------------------------------------------------ tendência
def supertrend(df: pd.DataFrame, periodo: int = 10, mult: float = 3.0):
    """Retorna (linha, direcao) onde direcao é +1 (alta) ou -1 (baixa)."""
    alta = df["maxima"].values
    baixa = df["minima"].values
    fech = df["fechamento"].values
    a = atr(df, periodo).values
    hl2 = (alta + baixa) / 2
    sup_b = hl2 + mult * a
    inf_b = hl2 - mult * a
    n = len(fech)
    sup_f = np.full(n, np.nan)
    inf_f = np.full(n, np.nan)
    direcao = np.zeros(n)
    linha = np.full(n, np.nan)
    for i in range(1, n):
        if np.isnan(a[i]):
            continue
        if np.isnan(inf_f[i - 1]):
            inf_f[i], sup_f[i], direcao[i] = inf_b[i], sup_b[i], 1
            linha[i] = inf_f[i]
            continue
        inf_f[i] = inf_b[i] if (inf_b[i] > inf_f[i - 1] or fech[i - 1] < inf_f[i - 1]) else inf_f[i - 1]
        sup_f[i] = sup_b[i] if (sup_b[i] < sup_f[i - 1] or fech[i - 1] > sup_f[i - 1]) else sup_f[i - 1]
        if direcao[i - 1] == 1:
            direcao[i] = -1 if fech[i] < inf_f[i] else 1
        else:
            direcao[i] = 1 if fech[i] > sup_f[i] else -1
        linha[i] = inf_f[i] if direcao[i] == 1 else sup_f[i]
    return pd.Series(linha, index=df.index), pd.Series(direcao, index=df.index)


def psar(df: pd.DataFrame, passo: float = 0.02, maximo: float = 0.2) -> pd.Series:
    alta = df["maxima"].values
    baixa = df["minima"].values
    fech = df["fechamento"].values
    n = len(fech)
    sar = np.full(n, np.nan)
    if n < 3:
        return pd.Series(sar, index=df.index)
    tendencia_alta = fech[1] > fech[0]
    ep = alta[0] if tendencia_alta else baixa[0]
    fa = passo
    sar[0] = baixa[0] if tendencia_alta else alta[0]
    for i in range(1, n):
        anterior = sar[i - 1]
        novo = anterior + fa * (ep - anterior)
        if tendencia_alta:
            novo = min(novo, baixa[i - 1], baixa[i - 2] if i >= 2 else baixa[i - 1])
            if baixa[i] < novo:
                tendencia_alta, novo, ep, fa = False, ep, baixa[i], passo
            elif alta[i] > ep:
                ep, fa = alta[i], min(fa + passo, maximo)
        else:
            novo = max(novo, alta[i - 1], alta[i - 2] if i >= 2 else alta[i - 1])
            if alta[i] > novo:
                tendencia_alta, novo, ep, fa = True, ep, alta[i], passo
            elif baixa[i] < ep:
                ep, fa = baixa[i], min(fa + passo, maximo)
        sar[i] = novo
    return pd.Series(sar, index=df.index)


def ichimoku(df: pd.DataFrame, tenkan: int = 9, kijun: int = 26, senkou: int = 52):
    def meio(p):
        return (df["maxima"].rolling(p).max() + df["minima"].rolling(p).min()) / 2
    linha_tenkan = meio(tenkan)
    linha_kijun = meio(kijun)
    span_a = ((linha_tenkan + linha_kijun) / 2).shift(kijun)
    span_b = meio(senkou).shift(kijun)
    return linha_tenkan, linha_kijun, span_a, span_b
