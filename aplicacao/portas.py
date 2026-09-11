"""Portas (interfaces) que a camada de aplicação exige da infraestrutura."""
from __future__ import annotations

from typing import Optional, Protocol

import pandas as pd

from dominio.modelos import InformacoesConta, Posicao


class ProvedorDados(Protocol):
    def obter_candles(self, ativo: str, timeframe: str, quantidade: int) -> pd.DataFrame:
        """Retorna DataFrame com colunas abertura, maxima, minima, fechamento, volume e índice de tempo."""
        ...


class Corretora(Protocol):
    def obter_conta(self) -> InformacoesConta: ...
    def obter_posicao(self, ativo: str) -> Optional[Posicao]: ...
    def enviar_ordem(self, ativo: str, direcao: int, contratos: float, stop: float, alvo: float,
                     comentario: str = "") -> bool: ...
    def fechar_posicao(self, ativo: str, motivo: str = "") -> bool: ...
    def lucro_do_dia(self, ativo: str) -> float: ...
