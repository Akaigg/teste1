"""
Motor de backtest barra a barra.

Regras de simulação (conservadoras, sem olhar o futuro) — espelham o executor
ao vivo para evitar "trades fantasmas" (trades que só existem no backtest):
  - sinal na barra i => entrada na ABERTURA da barra i+1 (ao vivo: ordem a
    mercado assim que o candle i fecha);
  - entradas apenas se a barra i+1 estiver dentro da janela de horário
    configurada em execucao.horario_inicio/fim (mesma regra do executor);
  - stop e alvo são verificados contra máxima/mínima de cada barra; se ambos
    forem atingidos na mesma barra, assume-se o STOP (pior caso); o stop vira
    ordem a mercado e por isso sofre deslizamento, o alvo (ordem limitada) não;
  - saídas adicionais: último candle do dia/da janela, sinal contrário,
    tempo máximo em posição;
  - após qualquer saída na barra j o sinal da própria barra j é avaliado
    (ao vivo, um stop intrabarra deixa o robô zerado e apto a entrar no
    fechamento daquele mesmo candle);
  - perda máxima diária (execucao.perda_maxima_diaria) bloqueia novas
    entradas no restante do dia, como ao vivo;
  - sinais cujo stop ou alvo ficariam a menos de `distancia_minima_stop`
    pontos do preço são descartados (o MT5 rejeitaria a ordem);
  - com `um_trade_por_vez` ligado, após uma saída na barra j a próxima
    entrada só pode vir de sinal da barra j+1 em diante (ao vivo o robô
    espera o candle seguinte com o ativo zerado); desligado, o sinal da
    própria barra j pode reverter a posição;
  - custos e deslizamento são descontados em pontos.
"""
from __future__ import annotations

from datetime import time as hora_do_dia
from typing import Optional, Tuple

import numpy as np
import pandas as pd

from aplicacao.metricas import calcular_metricas
from config.configuracao import ConfiguracaoBacktest
from dominio import indicadores as ind
from dominio.estrategias.base import EstrategiaBase
from dominio.modelos import ResultadoBacktest, Trade


class Backtester:
    def __init__(self, cfg: ConfiguracaoBacktest, valor_ponto: float, custo_pontos: float,
                 deslizamento_pontos: float, contratos: int, capital_inicial: float,
                 horario_inicio: str = "", horario_fim: str = "", perda_maxima_diaria: float = 0.0,
                 distancia_minima_stop: float = 0.0, um_trade_por_vez: bool = True):
        self.cfg = cfg
        self.valor_ponto = valor_ponto
        self.custo_pontos = custo_pontos
        self.deslizamento = deslizamento_pontos
        self.contratos = contratos
        self.capital_inicial = capital_inicial
        self.horario_inicio = self._parse_hora(horario_inicio)
        self.horario_fim = self._parse_hora(horario_fim)
        self.perda_maxima_diaria = abs(perda_maxima_diaria or 0.0)
        self.distancia_minima_stop = max(0.0, float(distancia_minima_stop or 0.0))
        self.um_trade_por_vez = bool(um_trade_por_vez)

    @staticmethod
    def _parse_hora(texto: str) -> Optional[hora_do_dia]:
        if not texto:
            return None
        h, m = texto.split(":")
        return hora_do_dia(int(h), int(m))

    def _mascara_horario(self, df: pd.DataFrame) -> np.ndarray:
        """True nas barras cujo horário de abertura está dentro da janela de operação."""
        if self.horario_inicio is None or self.horario_fim is None:
            return np.ones(len(df), dtype=bool)
        horas = df.index.time
        return np.array([self.horario_inicio <= h <= self.horario_fim for h in horas], dtype=bool)

    # ------------------------------------------------------------ preparação
    def preparar(self, df: pd.DataFrame, estrategia: EstrategiaBase) -> Tuple[np.ndarray, np.ndarray]:
        """Calcula sinais e ATR uma única vez (reaproveitado pela grade de stop/alvo)."""
        sinais = estrategia.sinais_limpos(df).values.astype(int)
        valores_atr = ind.atr(df, estrategia.periodo_atr).values.astype(float)
        return sinais, valores_atr

    def executar(self, df: pd.DataFrame, estrategia: EstrategiaBase,
                 mult_stop: Optional[float] = None, mult_alvo: Optional[float] = None,
                 filtro_ia=None, caracteristicas=None) -> ResultadoBacktest:
        sinais, valores_atr = self.preparar(df, estrategia)
        entradas = None
        if filtro_ia is not None and getattr(filtro_ia, "modelo", None) is not None:
            from ia.filtro_ml import extrair_caracteristicas
            car = caracteristicas if caracteristicas is not None else extrair_caracteristicas(df)
            entradas = filtro_ia.filtrar_sinais(car, sinais)
        return self.simular(df, estrategia, sinais, valores_atr,
                            mult_stop if mult_stop is not None else estrategia.mult_stop,
                            mult_alvo if mult_alvo is not None else estrategia.mult_alvo, sinais_entrada=entradas)

    # ------------------------------------------------------------- simulação
    def simular(self, df: pd.DataFrame, estrategia: EstrategiaBase, sinais: np.ndarray,
                valores_atr: np.ndarray, mult_stop: float, mult_alvo: float,
                sinais_entrada: Optional[np.ndarray] = None) -> ResultadoBacktest:
        """`sinais_entrada` (opcional) são os sinais após o veto da IA: valem só para abrir posição;
        saídas por sinal contrário continuam usando `sinais`, como faz o executor."""
        entradas = sinais if sinais_entrada is None else sinais_entrada
        abertura = df["abertura"].values
        maxima = df["maxima"].values
        minima = df["minima"].values
        fechamento = df["fechamento"].values
        dias = df.index.normalize().values
        tempos = df.index
        n = len(df)
        cfg = self.cfg
        trades = []
        na_janela = self._mascara_horario(df)
        # a barra j é a última "operável" do dia se a próxima muda de dia ou sai da janela de horário
        ultima_do_dia = np.ones(n, dtype=bool)
        ultima_do_dia[:-1] = (dias[1:] != dias[:-1]) | ~na_janela[1:]
        resultado_por_dia: dict = {}
        descartados_stop_minimo = 0

        i = 0
        while i < n - 1:
            s = int(entradas[i])
            a = valores_atr[i]
            if s == 0 or not np.isfinite(a) or a <= 0:
                i += 1
                continue
            if not na_janela[i + 1]:
                i += 1  # ao vivo o executor não entra fora da janela de horário
                continue
            if cfg.fechar_fim_dia and dias[i + 1] != dias[i]:
                i += 1  # não abre posição que atravessaria a virada do dia
                continue
            if self.perda_maxima_diaria and resultado_por_dia.get(dias[i + 1], 0.0) <= -self.perda_maxima_diaria:
                i += 1  # trava diária: sem novas entradas até o dia seguinte
                continue

            if self.distancia_minima_stop and (a * mult_stop < self.distancia_minima_stop
                                               or a * mult_alvo < self.distancia_minima_stop):
                descartados_stop_minimo += 1  # o MT5 rejeitaria: stop/alvo abaixo da distância mínima
                i += 1
                continue

            entrada = i + 1
            preco_entrada = abertura[entrada] + s * self.deslizamento
            stop = preco_entrada - s * a * mult_stop
            alvo = preco_entrada + s * a * mult_alvo

            j = entrada
            preco_saida, motivo = None, ""
            while j < n:
                if s == 1:
                    bateu_stop, bateu_alvo = minima[j] <= stop, maxima[j] >= alvo
                else:
                    bateu_stop, bateu_alvo = maxima[j] >= stop, minima[j] <= alvo
                if bateu_stop:
                    preco_saida, motivo = stop - s * self.deslizamento, "stop"
                    break
                if bateu_alvo:
                    preco_saida, motivo = alvo, "alvo"
                    break
                if cfg.fechar_fim_dia and ultima_do_dia[j]:
                    preco_saida, motivo = fechamento[j] - s * self.deslizamento, "fim_dia"
                    break
                if cfg.sair_sinal_contrario and sinais[j] == -s:
                    preco_saida, motivo = fechamento[j] - s * self.deslizamento, "sinal_contrario"
                    break
                if cfg.max_barras_posicao and (j - entrada + 1) >= cfg.max_barras_posicao:
                    preco_saida, motivo = fechamento[j] - s * self.deslizamento, "tempo"
                    break
                j += 1
            if preco_saida is None:
                j = n - 1
                preco_saida, motivo = fechamento[j], "fim_dados"

            pontos = s * (preco_saida - preco_entrada) - self.custo_pontos
            financeiro = float(pontos * self.valor_ponto * self.contratos)
            resultado_por_dia[dias[j]] = resultado_por_dia.get(dias[j], 0.0) + financeiro
            trades.append(Trade(
                estrategia=estrategia.nome, direcao=s, indice_entrada=entrada, indice_saida=j,
                data_entrada=tempos[entrada], data_saida=tempos[j], preco_entrada=float(preco_entrada),
                preco_saida=float(preco_saida), stop=float(stop), alvo=float(alvo), contratos=self.contratos,
                resultado_pontos=float(pontos), resultado_financeiro=financeiro, motivo_saida=motivo))
            # um_trade_por_vez: só sinais a partir da barra seguinte à saída; senão o sinal da barra j pode reverter
            i = j + 1 if self.um_trade_por_vez else j

        metricas = calcular_metricas(trades, self.capital_inicial)
        metricas["sinais_descartados_stop_minimo"] = descartados_stop_minimo
        return ResultadoBacktest(estrategia=estrategia.nome, mult_stop=mult_stop, mult_alvo=mult_alvo,
                                 trades=trades, metricas=metricas, n_barras=n,
                                 sinais_descartados_stop_minimo=descartados_stop_minimo)
