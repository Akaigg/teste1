"""Registro (logging) em console e arquivo."""
from __future__ import annotations

import logging
import os
import sys
from datetime import datetime

from config.caminhos import caminho

PASTA_REGISTROS = caminho("registros")


def obter_registrador(nome: str = "robo") -> logging.Logger:
    registrador = logging.getLogger(nome)
    if registrador.handlers:
        return registrador
    registrador.setLevel(logging.INFO)
    os.makedirs(PASTA_REGISTROS, exist_ok=True)
    formato = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s", "%Y-%m-%d %H:%M:%S")
    arquivo = logging.FileHandler(os.path.join(PASTA_REGISTROS, f"robo_{datetime.now():%Y%m%d}.log"), encoding="utf-8")
    arquivo.setFormatter(formato)
    registrador.addHandler(arquivo)
    if sys.stderr is not None:  # o executável em modo janela não tem console
        console = logging.StreamHandler()
        console.setFormatter(formato)
        registrador.addHandler(console)
    return registrador
