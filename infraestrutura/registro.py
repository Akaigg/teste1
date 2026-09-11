"""Registro (logging) em console e arquivo."""
from __future__ import annotations

import logging
import os
from datetime import datetime

PASTA_REGISTROS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "registros")


def obter_registrador(nome: str = "robo") -> logging.Logger:
    registrador = logging.getLogger(nome)
    if registrador.handlers:
        return registrador
    registrador.setLevel(logging.INFO)
    os.makedirs(PASTA_REGISTROS, exist_ok=True)
    formato = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s", "%Y-%m-%d %H:%M:%S")
    arquivo = logging.FileHandler(os.path.join(PASTA_REGISTROS, f"robo_{datetime.now():%Y%m%d}.log"), encoding="utf-8")
    arquivo.setFormatter(formato)
    console = logging.StreamHandler()
    console.setFormatter(formato)
    registrador.addHandler(arquivo)
    registrador.addHandler(console)
    return registrador
