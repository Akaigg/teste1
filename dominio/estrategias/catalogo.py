"""
Catálogo: ponto único de acesso a todas as estratégias disponíveis.

Para adicionar uma estratégia nova basta criar a classe em um dos módulos
(ou em um módulo novo) e incluí-la na função `registrar()` daquele módulo.
"""
from __future__ import annotations

from typing import Dict, List, Optional

from dominio.estrategias import (hibridas, momentum, padroes_candle, reversao, rompimento,
                                 tendencia, volatilidade, volume)
from dominio.estrategias.base import EstrategiaBase

_MODULOS = [tendencia, reversao, rompimento, volatilidade, momentum, volume, padroes_candle, hibridas]


def construir_catalogo() -> List[EstrategiaBase]:
    estrategias: List[EstrategiaBase] = []
    nomes = set()
    for modulo in _MODULOS:
        for estrategia in modulo.registrar():
            if estrategia.nome in nomes:
                raise ValueError(f"Nome de estratégia duplicado: {estrategia.nome}")
            nomes.add(estrategia.nome)
            estrategias.append(estrategia)
    return estrategias


def obter_estrategia(nome: str) -> Optional[EstrategiaBase]:
    for e in construir_catalogo():
        if e.nome == nome:
            return e
    return None


def familias() -> Dict[str, int]:
    contagem: Dict[str, int] = {}
    for e in construir_catalogo():
        contagem[e.familia] = contagem.get(e.familia, 0) + 1
    return contagem
