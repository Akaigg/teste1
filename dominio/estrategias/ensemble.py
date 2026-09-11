"""
ENSEMBLE: combina o viés contínuo de várias estratégias de famílias diferentes
(tendência, momentum/volume, fluxo, regressão, multi-timeframe, força do candle)
numa única pontuação ponderada. Entra quando a pontuação cruza o limiar e um
número mínimo de estratégias-membro concorda na direção.
"""
from __future__ import annotations

import pandas as pd

from dominio import indicadores as ind
from dominio.estrategias.base import (EstrategiaBase, concordancia, cruzou_abaixo, cruzou_acima, montar_sinais,
                                      pontuacao_ponderada)
from dominio.estrategias.confluencia import ConfluenciaMultiTimeframe
from dominio.estrategias.estatistica import CanalRegressao
from dominio.estrategias.estrutura import ForcaCandleComposta
from dominio.estrategias.fluxo import FluxoPonderado
from dominio.estrategias.pontuacao import ScoreMomentumVolume, ScoreTendencia


class EnsembleEstrategias(EstrategiaBase):
    identificador = "ensemble"
    familia = "ensemble"
    descricao = ("Média ponderada do viés de 6 estratégias-membro: score de tendência (1.5), momentum+volume (1.0), fluxo "
                 "ponderado (1.0), canal de regressão (1.0), confluência multi-timeframe (1.5) e força do candle (0.5). "
                 "Entra no cruzamento do limiar quando ≥ mínimo de membros concorda; filtro de regime de volatilidade.")
    stop_atr_padrao, alvo_atr_padrao = 2.0, 3.0

    def __init__(self, **parametros):
        super().__init__(**parametros)
        self.membros = {
            "tendencia": (ScoreTendencia(curta=9, media=21, longa=55, limiar=0.35), 1.5),
            "momentum": (ScoreMomentumVolume(periodo=10, limiar=0.30, mult_volume=1.0), 1.0),
            "fluxo": (FluxoPonderado(periodo=10, limiar=0.30), 1.0),
            "regressao": (CanalRegressao(periodo=50, r2_min=0.6, desvios=1.5), 1.0),
            "multi_tf": (ConfluenciaMultiTimeframe(fator1=self.p("fator_tf"), fator2=self.p("fator_tf") * 4), 1.5),
            "candle": (ForcaCandleComposta(amplitude_atr=0.8, limiar=0.45), 0.5),
        }

    def barras_minimas(self) -> int:
        return max([super().barras_minimas()] + [m.barras_minimas() for m, _ in self.membros.values()])

    def _componentes(self, df):
        return {nome: (m.vies(df), peso) for nome, (m, peso) in self.membros.items()}

    def vies(self, df):
        return pontuacao_ponderada(self._componentes(df))

    def gerar_sinais(self, df):
        comp = self._componentes(df)
        score = pontuacao_ponderada(comp)
        lim, minimo = self.p("limiar"), self.p("minimo_membros")
        pct_atr = ind.percentil(ind.atr(df, 14), 200)
        regime_ok = (pct_atr >= 0.10) & (pct_atr <= 0.95)
        compras = cruzou_acima(score, lim) & (concordancia(comp, 1, 0.15) >= minimo) & regime_ok
        vendas = cruzou_abaixo(score, -lim) & (concordancia(comp, -1, 0.15) >= minimo) & regime_ok
        return montar_sinais(compras, vendas)


def registrar():
    e = []
    for lim, mm, ft in [(0.30, 4, 3), (0.40, 4, 3), (0.25, 3, 2), (0.35, 5, 4)]:
        e.append(EnsembleEstrategias(limiar=lim, minimo_membros=mm, fator_tf=ft))
    return e
