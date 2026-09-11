"""
Pasta base onde o robô grava configuração, resultados e registros.

Rodando pelo código-fonte é a raiz do projeto; rodando como executável
(PyInstaller) é a pasta onde está o .exe — assim os arquivos ficam ao lado do
programa e não na pasta temporária de extração.
"""
from __future__ import annotations

import os
import sys


def pasta_base() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def caminho(*partes: str) -> str:
    return os.path.join(pasta_base(), *partes)
