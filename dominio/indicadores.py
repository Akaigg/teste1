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


# ------------------------------------------------------------ regime / eficiência
def eficiencia_kaufman(serie: pd.Series, periodo: int = 10) -> pd.Series:
    """Efficiency Ratio: deslocamento líquido / soma dos deslocamentos (1 = linha reta, 0 = ruído)."""
    liquido = (serie - serie.shift(periodo)).abs()
    caminho = serie.diff().abs().rolling(periodo).sum()
    return liquido / caminho.replace(0, np.nan)


def choppiness(df: pd.DataFrame, periodo: int = 14) -> pd.Series:
    """Choppiness Index (0-100): alto = mercado lateral, baixo = mercado direcional."""
    soma_tr = true_range(df).rolling(periodo).sum()
    faixa = (df["maxima"].rolling(periodo).max() - df["minima"].rolling(periodo).min()).replace(0, np.nan)
    return 100 * np.log10(soma_tr / faixa) / np.log10(periodo)


def percentil(serie: pd.Series, periodo: int) -> pd.Series:
    """Posição (0-1) do valor atual dentro da janela móvel."""
    return serie.rolling(periodo).rank(pct=True)


def autocorrelacao(serie: pd.Series, periodo: int, defasagem: int = 1) -> pd.Series:
    return serie.rolling(periodo).corr(serie.shift(defasagem))


# ------------------------------------------------------- regressão linear móvel
def _convolucao_movel(valores: np.ndarray, pesos: np.ndarray) -> np.ndarray:
    """Produto interno móvel (janela = len(pesos)); NaN até a janela estar completa ou se houver NaN nela."""
    n, p = len(valores), len(pesos)
    saida = np.full(n, np.nan)
    if n < p:
        return saida
    limpos = np.nan_to_num(valores)
    saida[p - 1:] = np.convolve(limpos, pesos[::-1], mode="valid")
    invalidos = np.convolve(np.isnan(valores).astype(float), np.ones(p), mode="valid") > 0
    saida[p - 1:][invalidos] = np.nan
    return saida


def regressao_linear(serie: pd.Series, periodo: int):
    """Regressão linear móvel de `serie` contra o tempo (0..periodo-1).

    Retorna (inclinacao, r2, valor_ajustado_na_ultima_barra, desvio_residual)."""
    x = np.arange(periodo, dtype=float)
    xm = x.mean()
    sxx = float(((x - xm) ** 2).sum())
    y = serie.values.astype(float)
    sxy = _convolucao_movel(y, (x - xm)) - 0.0  # sum((x-xm)*y) = sum((x-xm)*(y-ym)) pois sum(x-xm)=0
    inclinacao = sxy / sxx
    media_y = serie.rolling(periodo).mean().values
    syy = serie.rolling(periodo).var(ddof=0).values * periodo
    with np.errstate(invalid="ignore", divide="ignore"):
        r2 = np.where(syy > 0, (sxy ** 2) / (sxx * syy), 0.0)
        var_residual = np.maximum(syy - inclinacao ** 2 * sxx, 0.0) / periodo
    ajustado = media_y + inclinacao * (periodo - 1 - xm)
    idx = serie.index
    return (pd.Series(inclinacao, index=idx), pd.Series(r2, index=idx),
            pd.Series(ajustado, index=idx), pd.Series(np.sqrt(var_residual), index=idx))


def inclinacao(serie: pd.Series, periodo: int) -> pd.Series:
    return regressao_linear(serie, periodo)[0]


# ------------------------------------------------------------- volume / fluxo
def bandas_vwap(df: pd.DataFrame, desvios: float = 2.0):
    """VWAP diária com bandas de ±desvios desvios-padrão ponderados por volume."""
    dia = df.index.normalize()
    tp = (df["maxima"] + df["minima"] + df["fechamento"]) / 3
    v = df["volume"].groupby(dia).cumsum().replace(0, np.nan)
    media = (tp * df["volume"]).groupby(dia).cumsum() / v
    media_quad = (tp ** 2 * df["volume"]).groupby(dia).cumsum() / v
    dp = np.sqrt((media_quad - media ** 2).clip(lower=0))
    return media, media + desvios * dp, media - desvios * dp, dp


def delta_volume(df: pd.DataFrame, periodo: int = 10) -> pd.Series:
    """Proxy de delta agressor (-1..1): posição do fechamento na amplitude x volume, acumulado em N barras."""
    faixa = (df["maxima"] - df["minima"]).replace(0, np.nan)
    posicao = (2 * (df["fechamento"] - df["minima"]) / faixa - 1).fillna(0)
    return (posicao * df["volume"]).rolling(periodo).sum() / df["volume"].rolling(periodo).sum().replace(0, np.nan)


def barra_do_dia(df: pd.DataFrame) -> pd.Series:
    """Número sequencial (0, 1, 2...) do candle dentro do dia."""
    return pd.Series(df.groupby(df.index.normalize()).cumcount().values, index=df.index)


# ------------------------------------------------------- pivôs / estrutura
def pivos(df: pd.DataFrame, esquerda: int = 5, direita: int = 5):
    """Topos e fundos confirmados sem olhar o futuro.

    Um fundo em i só é conhecido em i+direita; a série retornada marca o valor do
    pivô NA BARRA DE CONFIRMAÇÃO (NaN nas demais). Retorna (topos, fundos)."""
    janela = esquerda + direita + 1
    max_janela = df["maxima"].rolling(janela).max()
    min_janela = df["minima"].rolling(janela).min()
    centro_max = df["maxima"].shift(direita)
    centro_min = df["minima"].shift(direita)
    topos = centro_max.where(centro_max >= max_janela)
    fundos = centro_min.where(centro_min <= min_janela)
    return topos, fundos


def ultimos_dois(serie_pivos: pd.Series):
    """Para uma série esparsa de pivôs, devolve (último, penúltimo) propagados para frente."""
    validos = serie_pivos.dropna()
    ultimo = serie_pivos.ffill()
    penultimo = validos.shift(1).reindex(serie_pivos.index).ffill()
    return ultimo, penultimo


def reamostrar_superior(df: pd.DataFrame, fator: int) -> pd.DataFrame:
    """Agrega candles em timeframe `fator` vezes maior (por tempo). Inclui a barra em formação;
    use shift(1) antes de reindexar para usar apenas barras superiores concluídas."""
    if len(df) < 3:
        return df.copy()
    minutos = int(max(1, round(pd.Series(df.index).diff().dropna().median().total_seconds() / 60)))
    regra = f"{minutos * fator}min"
    agregado = df.resample(regra, label="left", closed="left", origin="start_day").agg(
        {"abertura": "first", "maxima": "max", "minima": "min", "fechamento": "last", "volume": "sum"})
    return agregado.dropna(subset=["fechamento"])


def alinhar_superior(serie_superior: pd.Series, indice_base: pd.DatetimeIndex) -> pd.Series:
    """Leva uma série do timeframe superior para o índice base usando só barras superiores CONCLUÍDAS."""
    return serie_superior.shift(1).reindex(indice_base, method="ffill")
