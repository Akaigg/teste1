"""
Classe base de todas as estratégias e utilitários para construção de sinais.

Contrato de uma estratégia:
  - gerar_sinais(df) -> pd.Series alinhada ao índice do df com valores
    1 (compra), -1 (venda) ou 0 (nada). O sinal na barra i é executado na
    abertura da barra i+1 (sem olhar o futuro).
  - stop e alvo são calculados automaticamente a partir do ATR com
    multiplicadores próprios de cada estratégia, que são ajustados pelo
    seletor com base em backtest.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Tuple

import numpy as np
import pandas as pd

from dominio import indicadores as ind


# ------------------------------------------------------------- utilitários
def cruzou_acima(a: pd.Series, b) -> pd.Series:
    return (a > b) & (a.shift(1) <= (b.shift(1) if isinstance(b, pd.Series) else b))


def cruzou_abaixo(a: pd.Series, b) -> pd.Series:
    return (a < b) & (a.shift(1) >= (b.shift(1) if isinstance(b, pd.Series) else b))


def entrou_em(condicao: pd.Series) -> pd.Series:
    """Verdadeiro apenas na primeira barra em que a condição passa a valer."""
    condicao = condicao.fillna(False).astype(bool)
    return condicao & ~condicao.shift(1, fill_value=False)


def montar_sinais(compras: pd.Series, vendas: pd.Series) -> pd.Series:
    sinais = pd.Series(0, index=compras.index, dtype=int)
    sinais[compras.fillna(False).astype(bool)] = 1
    sinais[vendas.fillna(False).astype(bool)] = -1
    return sinais


def normalizar(serie: pd.Series, escala: float) -> pd.Series:
    """Comprime um valor para o intervalo (-1, 1) com tanh; `escala` é o valor que vira ~0.76."""
    return np.tanh(serie / escala)


def limitar(serie: pd.Series, minimo: float = -1.0, maximo: float = 1.0) -> pd.Series:
    return serie.clip(lower=minimo, upper=maximo)


def pontuacao_ponderada(componentes: dict) -> pd.Series:
    """Média ponderada de componentes já normalizados em [-1, 1].

    `componentes` = {nome: (serie, peso)}. O resultado fica em [-1, 1]; é NaN
    enquanto qualquer componente ainda estiver em aquecimento, para que a
    pontuação nunca seja calculada com indicadores parciais."""
    series = pd.concat({n: s * p for n, (s, p) in componentes.items()}, axis=1)
    total_pesos = sum(p for _, p in componentes.values())
    return series.sum(axis=1, skipna=False) / total_pesos


def concordancia(componentes: dict, direcao: int, minimo: float = 0.2) -> pd.Series:
    """Quantos componentes apontam na direção (+1/-1) com intensidade mínima."""
    series = pd.concat({n: (s * direcao >= minimo).astype(int) for n, (s, _) in componentes.items()}, axis=1)
    return series.sum(axis=1)


def gatilho_por_limiar(pontuacao: pd.Series, limiar: float) -> pd.Series:
    """Sinais quando a pontuação cruza +limiar (compra) ou -limiar (venda)."""
    return montar_sinais(cruzou_acima(pontuacao, limiar), cruzou_abaixo(pontuacao, -limiar))


# --------------------------------------------------------------- base
class EstrategiaBase(ABC):
    identificador: str = "base"
    familia: str = "generica"
    descricao: str = ""
    stop_atr_padrao: float = 2.0
    alvo_atr_padrao: float = 3.0
    periodo_atr: int = 14

    def __init__(self, **parametros):
        self.parametros = parametros
        self.mult_stop = self.stop_atr_padrao
        self.mult_alvo = self.alvo_atr_padrao

    # ---- identidade
    @property
    def nome(self) -> str:
        sufixo = "_".join(str(v).replace(".", "p") for v in self.parametros.values())
        return f"{self.identificador}_{sufixo}" if sufixo else self.identificador

    def p(self, chave: str):
        return self.parametros[chave]

    def barras_minimas(self) -> int:
        """Barras necessárias para os indicadores convergirem (os filtros de regime usam percentis de 200 barras)."""
        maiores = [v for v in self.parametros.values() if isinstance(v, (int, float)) and v > 1]
        return int(max(maiores + [100])) * 3 + self.periodo_atr + 30

    # ---- sinais
    @abstractmethod
    def gerar_sinais(self, df: pd.DataFrame) -> pd.Series:
        ...

    def sinais_limpos(self, df: pd.DataFrame) -> pd.Series:
        return self.gerar_sinais(df).reindex(df.index).fillna(0).astype(int)

    def vies(self, df: pd.DataFrame):
        """Viés contínuo em [-1, 1] (positivo = altista) usado pelo ensemble.
        Estratégias sem pontuação contínua retornam None."""
        return None

    # ---- risco
    def configurar_risco(self, mult_stop: float, mult_alvo: float) -> None:
        self.mult_stop = float(mult_stop)
        self.mult_alvo = float(mult_alvo)

    def calcular_stop_alvo(self, df: pd.DataFrame, direcao: int, preco_entrada: float,
                           indice: int = -1) -> Tuple[float, float]:
        valor_atr = float(ind.atr(df, self.periodo_atr).iloc[indice])
        if not np.isfinite(valor_atr) or valor_atr <= 0:
            valor_atr = float((df["maxima"] - df["minima"]).tail(self.periodo_atr).mean())
        stop = preco_entrada - direcao * valor_atr * self.mult_stop
        alvo = preco_entrada + direcao * valor_atr * self.mult_alvo
        return stop, alvo

    def descrever(self) -> dict:
        return {
            "nome": self.nome,
            "familia": self.familia,
            "descricao": self.descricao,
            "parametros": dict(self.parametros),
            "mult_stop": self.mult_stop,
            "mult_alvo": self.mult_alvo,
        }
