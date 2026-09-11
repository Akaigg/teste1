"""Entidades e objetos de valor do domínio de trading."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import IntEnum
from typing import List, Optional

import pandas as pd


class Direcao(IntEnum):
    COMPRA = 1
    VENDA = -1
    NEUTRO = 0


@dataclass
class Trade:
    """Uma operação completa (entrada e saída) gerada em backtest."""
    estrategia: str
    direcao: int
    indice_entrada: int
    indice_saida: int
    data_entrada: pd.Timestamp
    data_saida: pd.Timestamp
    preco_entrada: float
    preco_saida: float
    stop: float
    alvo: float
    contratos: int
    resultado_pontos: float
    resultado_financeiro: float
    motivo_saida: str

    def para_dict(self) -> dict:
        d = asdict(self)
        d["data_entrada"] = str(self.data_entrada)
        d["data_saida"] = str(self.data_saida)
        return d


@dataclass
class ResultadoBacktest:
    estrategia: str
    mult_stop: float
    mult_alvo: float
    trades: List[Trade]
    metricas: dict
    n_barras: int
    sinais_descartados_stop_minimo: int = 0

    def curva_capital(self, capital_inicial: float) -> List[float]:
        curva = [capital_inicial]
        for t in self.trades:
            curva.append(curva[-1] + t.resultado_financeiro)
        return curva


@dataclass
class Posicao:
    ativo: str
    direcao: int
    contratos: float
    preco_entrada: float
    stop: float
    alvo: float
    ticket: int = 0
    data_abertura: Optional[pd.Timestamp] = None


@dataclass
class InformacoesConta:
    login: int = 0
    nome: str = ""
    servidor: str = ""
    saldo: float = 0.0
    patrimonio: float = 0.0
    moeda: str = ""
    alavancagem: int = 0

    def descrever(self) -> str:
        return (f"Conta {self.login} ({self.nome}) @ {self.servidor} | "
                f"Saldo: {self.saldo:.2f} {self.moeda} | Patrimônio: {self.patrimonio:.2f}")
