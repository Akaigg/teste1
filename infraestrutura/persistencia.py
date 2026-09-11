"""Persistência de rankings e da estratégia selecionada em JSON."""
from __future__ import annotations

import json
import os
from datetime import datetime
from typing import List, Optional

import numpy as np

from config.caminhos import caminho

PASTA_RESULTADOS = caminho("resultados")


def _serializar(obj):
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    return str(obj)


def _caminho_ranking(ativo: str, timeframe: str) -> str:
    os.makedirs(PASTA_RESULTADOS, exist_ok=True)
    seguro = "".join(c if c.isalnum() else "_" for c in ativo) or "sem_ativo"
    return os.path.join(PASTA_RESULTADOS, f"ranking_{seguro}_{timeframe}.json")


def salvar_ranking(ranking: List[dict], ativo: str, timeframe: str, info_dados: dict) -> str:
    caminho = _caminho_ranking(ativo, timeframe)
    conteudo = {"ativo": ativo, "timeframe": timeframe, "gerado_em": datetime.now().isoformat(timespec="seconds"),
                "dados": info_dados, "ranking": ranking}
    with open(caminho, "w", encoding="utf-8") as arq:
        json.dump(conteudo, arq, indent=2, ensure_ascii=False, default=_serializar)
    return caminho


def carregar_ranking(ativo: str, timeframe: str) -> Optional[dict]:
    caminho = _caminho_ranking(ativo, timeframe)
    if not os.path.exists(caminho):
        return None
    with open(caminho, "r", encoding="utf-8") as arq:
        return json.load(arq)


def salvar_walkforward(resultado: dict, ativo: str, timeframe: str) -> str:
    os.makedirs(PASTA_RESULTADOS, exist_ok=True)
    seguro = "".join(c if c.isalnum() else "_" for c in ativo) or "sem_ativo"
    caminho = os.path.join(PASTA_RESULTADOS, f"walkforward_{seguro}_{timeframe}_{resultado['estrategia']}.json")
    conteudo = {"ativo": ativo, "timeframe": timeframe, "gerado_em": datetime.now().isoformat(timespec="seconds"),
                "resultado": resultado}
    with open(caminho, "w", encoding="utf-8") as arq:
        json.dump(conteudo, arq, indent=2, ensure_ascii=False, default=_serializar)
    return caminho


def salvar_trades(trades: List[dict], nome_estrategia: str) -> str:
    os.makedirs(PASTA_RESULTADOS, exist_ok=True)
    caminho = os.path.join(PASTA_RESULTADOS, f"trades_{nome_estrategia}.json")
    with open(caminho, "w", encoding="utf-8") as arq:
        json.dump(trades, arq, indent=2, ensure_ascii=False, default=_serializar)
    return caminho
