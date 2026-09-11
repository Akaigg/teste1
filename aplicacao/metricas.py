"""Métricas de desempenho calculadas sobre uma lista de trades."""
from __future__ import annotations

from typing import List

import numpy as np

from dominio.modelos import Trade


def calcular_metricas(trades: List[Trade], capital_inicial: float) -> dict:
    n = len(trades)
    if n == 0:
        return {"total_trades": 0, "lucro_liquido": 0.0, "fator_lucro": 0.0, "taxa_acerto": 0.0,
                "drawdown_maximo": 0.0, "drawdown_maximo_pct": 0.0, "expectativa": 0.0,
                "payoff": 0.0, "sharpe": 0.0, "retorno_pct": 0.0, "max_perdas_seguidas": 0,
                "fator_recuperacao": 0.0, "media_ganho": 0.0, "media_perda": 0.0}
    resultados = np.array([t.resultado_financeiro for t in trades], dtype=float)
    ganhos = resultados[resultados > 0]
    perdas = resultados[resultados <= 0]
    lucro_bruto = float(ganhos.sum())
    prejuizo_bruto = float(-perdas.sum())
    lucro_liquido = float(resultados.sum())

    curva = capital_inicial + np.cumsum(resultados)
    pico = np.maximum.accumulate(np.concatenate([[capital_inicial], curva]))
    quedas = pico[1:] - curva
    dd_max = float(quedas.max()) if len(quedas) else 0.0
    dd_pct = float((quedas / pico[1:]).max() * 100) if len(quedas) else 0.0

    seguidas, max_seguidas = 0, 0
    for r in resultados:
        seguidas = seguidas + 1 if r <= 0 else 0
        max_seguidas = max(max_seguidas, seguidas)

    media_ganho = float(ganhos.mean()) if len(ganhos) else 0.0
    media_perda = float(perdas.mean()) if len(perdas) else 0.0
    desvio = float(resultados.std(ddof=1)) if n > 1 else 0.0
    return {
        "total_trades": n,
        "vencedores": int(len(ganhos)),
        "perdedores": int(len(perdas)),
        "taxa_acerto": float(len(ganhos) / n * 100),
        "lucro_bruto": lucro_bruto,
        "prejuizo_bruto": prejuizo_bruto,
        "lucro_liquido": lucro_liquido,
        "fator_lucro": float(lucro_bruto / prejuizo_bruto) if prejuizo_bruto > 0 else (99.0 if lucro_bruto > 0 else 0.0),
        "media_ganho": media_ganho,
        "media_perda": media_perda,
        "payoff": float(media_ganho / abs(media_perda)) if media_perda != 0 else 0.0,
        "expectativa": float(resultados.mean()),
        "drawdown_maximo": dd_max,
        "drawdown_maximo_pct": dd_pct,
        "sharpe": float(resultados.mean() / desvio * np.sqrt(n)) if desvio > 0 else 0.0,
        "retorno_pct": float(lucro_liquido / capital_inicial * 100),
        "max_perdas_seguidas": int(max_seguidas),
        "fator_recuperacao": float(lucro_liquido / dd_max) if dd_max > 0 else 0.0,
    }
