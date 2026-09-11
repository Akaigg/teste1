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
        maiores = [v for v in self.parametros.values() if isinstance(v, (int, float)) and v > 1]
        return int(max(maiores + [50])) * 3 + self.periodo_atr + 30

    # ---- sinais
    @abstractmethod
    def gerar_sinais(self, df: pd.DataFrame) -> pd.Series:
        ...

    def sinais_limpos(self, df: pd.DataFrame) -> pd.Series:
        return self.gerar_sinais(df).reindex(df.index).fillna(0).astype(int)

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
