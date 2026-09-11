"""
Filtro de IA (opcional): um RandomForest aprende, a partir dos trades de
backtest da estratégia escolhida, quais contextos de mercado tendem a gerar
trades vencedores. Requer scikit-learn (pip install scikit-learn).

Critério de veto (valor esperado): um trade vale a pena se
    p * ganho_medio - (1 - p) * perda_media > 0
ou seja, se p > perda_media / (ganho_medio + perda_media) = ponto de equilíbrio
da estratégia. O sinal é vetado quando a probabilidade prevista fica abaixo do
ponto de equilíbrio mais uma margem de segurança (ia.margem_probabilidade).
Um limiar absoluto (ex.: 55%) estaria errado: estratégias com 35% de acerto e
payoff alto são lucrativas e seriam vetadas inteiras.

Importante: é um filtro auxiliar, não uma garantia. Ele é treinado apenas em
dados passados e é reavaliado sempre que um novo ranking é gerado.
"""
from __future__ import annotations

from typing import List, Optional

import numpy as np
import pandas as pd

from dominio import indicadores as ind
from dominio.modelos import Trade

try:
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.model_selection import cross_val_score
    SKLEARN_DISPONIVEL = True
except ImportError:
    SKLEARN_DISPONIVEL = False


def extrair_caracteristicas(df: pd.DataFrame) -> pd.DataFrame:
    f = df["fechamento"]
    a = ind.atr(df, 14)
    car = pd.DataFrame(index=df.index)
    car["rsi14"] = ind.rsi(f, 14)
    car["rsi2"] = ind.rsi(f, 2)
    car["atr_rel"] = a / f
    car["dist_ema20"] = (f - ind.ema(f, 20)) / a
    car["dist_ema50"] = (f - ind.ema(f, 50)) / a
    car["dist_vwap"] = (f - ind.vwap(df)) / a
    car["roc5"] = ind.roc(f, 5)
    car["roc20"] = ind.roc(f, 20)
    car["adx14"] = ind.adx(df, 14)[0]
    car["vol_rel"] = df["volume"] / ind.sma(df["volume"], 20)
    car["amplitude_rel"] = (df["maxima"] - df["minima"]) / a
    car["hora"] = df.index.hour + df.index.minute / 60.0
    car["direcao_candle"] = np.sign(f - df["abertura"])
    return car.replace([np.inf, -np.inf], np.nan)


def _montar_matriz(caracteristicas: pd.DataFrame, indices, direcoes) -> np.ndarray:
    X = caracteristicas.values[np.asarray(indices, dtype=int)].astype(float)
    return np.nan_to_num(np.column_stack([X, np.asarray(direcoes, dtype=float)]))


class FiltroIA:
    def __init__(self, margem: float = 0.05, min_trades: int = 60, registrador=None, n_arvores: int = 200):
        self.margem = margem
        self.limiar = 0.5  # recalculado no treino: ponto de equilíbrio + margem
        self.min_trades = min_trades
        self.registrador = registrador
        self.n_arvores = n_arvores
        self.modelo: Optional[object] = None
        self.acuracia_cv: Optional[float] = None
        self.n_treino = 0

    def treinar(self, df: pd.DataFrame, trades: List[Trade], calcular_acuracia: bool = True,
                caracteristicas: Optional[pd.DataFrame] = None) -> bool:
        """Treina com os trades informados. Barra do sinal = indice_entrada - 1 (mesma referência do executor)."""
        if not SKLEARN_DISPONIVEL:
            if self.registrador:
                self.registrador.warning("scikit-learn não instalado; filtro de IA desativado.")
            return False
        if len(trades) < self.min_trades:
            if self.registrador:
                self.registrador.warning(f"Filtro de IA precisa de {self.min_trades} trades; há {len(trades)}. Desativado.")
            return False
        car = caracteristicas if caracteristicas is not None else extrair_caracteristicas(df)
        validos = [t for t in trades if t.indice_entrada >= 1]
        X = _montar_matriz(car, [t.indice_entrada - 1 for t in validos], [t.direcao for t in validos])
        y = np.array([1 if t.resultado_financeiro > 0 else 0 for t in validos])
        if len(set(y)) < 2:
            return False
        self.modelo = RandomForestClassifier(n_estimators=self.n_arvores, max_depth=5, min_samples_leaf=5, random_state=7)
        self.acuracia_cv = None
        if calcular_acuracia:
            try:
                self.acuracia_cv = float(cross_val_score(self.modelo, X, y, cv=min(5, len(y) // 10 or 2)).mean())
            except Exception:
                self.acuracia_cv = None
        self.modelo.fit(X, y)
        self.n_treino = int(len(y))
        ganhos = [t.resultado_financeiro for t in validos if t.resultado_financeiro > 0]
        perdas = [-t.resultado_financeiro for t in validos if t.resultado_financeiro <= 0]
        ganho_medio = float(np.mean(ganhos)) if ganhos else 0.0
        perda_media = float(np.mean(perdas)) if perdas else 0.0
        equilibrio = perda_media / (ganho_medio + perda_media) if (ganho_medio + perda_media) > 0 else 0.5
        self.limiar = float(min(0.95, equilibrio + self.margem))
        if self.registrador:
            texto = (f"Filtro de IA treinado com {len(y)} trades | ponto de equilíbrio {equilibrio:.0%} + margem "
                     f"{self.margem:.0%} = veta abaixo de {self.limiar:.0%}")
            if self.acuracia_cv is not None:
                texto += f" | acurácia CV ≈ {self.acuracia_cv:.1%}"
            self.registrador.info(texto + ".")
        return True

    def aprovar_lote(self, caracteristicas: pd.DataFrame, indices, direcoes) -> np.ndarray:
        """Vetor booleano: True nos sinais aprovados (probabilidade >= limiar). Sem modelo, aprova tudo."""
        indices = np.asarray(indices, dtype=int)
        if self.modelo is None or len(indices) == 0:
            return np.ones(len(indices), dtype=bool)
        prob = self.modelo.predict_proba(_montar_matriz(caracteristicas, indices, direcoes))[:, 1]
        return prob >= self.limiar

    def filtrar_sinais(self, caracteristicas: pd.DataFrame, sinais: np.ndarray) -> np.ndarray:
        """Cópia de `sinais` com os sinais vetados zerados (usada como sinais de ENTRADA no backtest)."""
        indices = np.flatnonzero(sinais != 0)
        aprovados = self.aprovar_lote(caracteristicas, indices, sinais[indices])
        filtrados = sinais.copy()
        filtrados[indices[~aprovados]] = 0
        return filtrados

    def probabilidade(self, df: pd.DataFrame, indice: int, direcao: int) -> float:
        if self.modelo is None:
            return 1.0
        car = extrair_caracteristicas(df.iloc[: indice + 1])
        X = _montar_matriz(car, [len(car) - 1], [direcao])
        return float(self.modelo.predict_proba(X)[0][1])

    def aprovar(self, df: pd.DataFrame, indice: int, direcao: int) -> bool:
        return self.probabilidade(df, indice, direcao) >= self.limiar
