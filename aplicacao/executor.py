"""
Executor de operação automática (ao vivo).

Ciclo: aguarda novo candle fechado -> calcula sinal da estratégia escolhida ->
gerencia saída (sinal contrário, horário, perda máxima diária) -> abre
posição com stop/alvo automáticos. Funciona com corretora real (MT5) ou
simulada (paper trading), pois depende apenas das portas da aplicação.
"""
from __future__ import annotations

import time
from datetime import datetime, time as hora_do_dia
from typing import Callable, Optional

import pandas as pd

from aplicacao.portas import Corretora, ProvedorDados
from config.configuracao import Configuracao
from dominio.estrategias.base import EstrategiaBase


_MINUTOS_TF = {"M1": 1, "M2": 2, "M3": 3, "M5": 5, "M10": 10, "M15": 15, "M30": 30, "H1": 60, "H4": 240, "D1": 1440}


def _parse_hora(texto: str) -> hora_do_dia:
    h, m = texto.split(":")
    return hora_do_dia(int(h), int(m))


class Executor:
    def __init__(self, config: Configuracao, estrategia: EstrategiaBase, provedor: ProvedorDados,
                 corretora: Corretora, registrador, filtro_ia=None,
                 reavaliador: Optional[Callable[[], Optional[EstrategiaBase]]] = None):
        self.cfg = config
        self.estrategia = estrategia
        self.provedor = provedor
        self.corretora = corretora
        self.log = registrador
        self.filtro_ia = filtro_ia
        self.reavaliador = reavaliador
        self._ultimo_candle: Optional[pd.Timestamp] = None
        self._ultima_reavaliacao = datetime.now()
        self._bloqueado_no_dia: Optional[pd.Timestamp] = None
        self.ativo = True
        self.intervalo = config.execucao.intervalo_segundos
        self._posicionado_antes = False   # havia posição (ou ordem enviada) no ciclo anterior
        self.distancia_minima_stop = 0.0

    # ------------------------------------------------------------ laço principal
    def iniciar(self) -> None:
        cfg = self.cfg
        self.log.info(f"Iniciando operação | {cfg.ativo} {cfg.timeframe} | estratégia={self.estrategia.nome} "
                      f"| stop={self.estrategia.mult_stop}xATR alvo={self.estrategia.mult_alvo}xATR "
                      f"| contratos={cfg.contratos} | modo={cfg.execucao.modo.upper()}")
        self.log.info(self.corretora.obter_conta().descrever())
        self.distancia_minima_stop = self._resolver_distancia_minima()
        self.log.info(f"Distância mínima de stop/alvo: {self.distancia_minima_stop:.0f} pontos | "
                      f"um trade por vez: {'sim' if cfg.execucao.um_trade_por_vez else 'não'}")
        self.log.info("Pressione Ctrl+C para encerrar.")
        try:
            while self.ativo:
                try:
                    self._ciclo()
                except Exception as erro:
                    self.log.error(f"Erro no ciclo: {erro}")
                self._aguardar(self.intervalo)
        except KeyboardInterrupt:
            self.log.info("Encerrado pelo usuário.")
            self._resumo_simulado()
        else:
            if not getattr(self.provedor, "terminou", False):
                self.log.info("Operação encerrada.")
                self._resumo_simulado()

    # ------------------------------------------------------------ um ciclo
    def _ciclo(self) -> None:
        cfg = self.cfg
        minimas = self.estrategia.barras_minimas()
        desejadas = max(minimas * 2, 1000)  # folga para o "aquecimento" de EMAs/RSI convergir ao valor do backtest
        df = self.provedor.obter_candles(cfg.ativo, cfg.timeframe, desejadas + 1)
        if getattr(self.provedor, "terminou", False):
            self.log.info("Replay concluído: fim dos dados históricos.")
            self._resumo_simulado()
            self.ativo = False
            return
        if df is None or len(df) < minimas + 1:
            self.log.warning(f"Dados insuficientes ({0 if df is None else len(df)}/{minimas + 1}).")
            return
        df = df.iloc[:-1]  # descarta o candle em formação
        ultimo = df.index[-1]
        candle = df.iloc[-1]
        if hasattr(self.corretora, "atualizar"):
            self.corretora.atualizar(candle, ultimo)  # simulador precisa do preço
        if ultimo == self._ultimo_candle:
            return
        minutos_tf = _MINUTOS_TF.get(cfg.timeframe.upper(), 5)
        if self._ultimo_candle is not None:
            pulados = int((ultimo - self._ultimo_candle) / pd.Timedelta(minutes=minutos_tf)) - 1
            if 0 < pulados < 12 * 60 / minutos_tf:  # dentro do mesmo pregão: o robô ficou sem processar candles
                self.log.warning(f"{pulados} candle(s) não processado(s) entre {self._ultimo_candle} e {ultimo}; "
                                 f"sinais desse intervalo foram perdidos (reduza o intervalo ou a carga do processo).")
        self._ultimo_candle = ultimo
        self._reavaliar_se_preciso()

        posicao = self.corretora.obter_posicao(cfg.ativo)
        # A decisão é tomada no fechamento do candle `ultimo`; a ordem executa na abertura do PRÓXIMO candle.
        # Por isso a janela de horário é avaliada sobre o próximo candle, exatamente como no backtest.
        proximo = ultimo + pd.Timedelta(minutes=minutos_tf)
        inicio, fim = _parse_hora(cfg.execucao.horario_inicio), _parse_hora(cfg.execucao.horario_fim)
        proximo_operavel = inicio <= proximo.time() <= fim and proximo.normalize() == ultimo.normalize()
        if not proximo_operavel and cfg.backtest.fechar_fim_dia:
            if posicao is not None:
                self.log.info("Último candle da janela de operação: encerrando posição (fim_dia).")
                self.corretora.fechar_posicao(cfg.ativo, "fim_dia")
            self._posicionado_antes = False
            return

        if self._trava_diaria_atingida(ultimo, posicao):
            self._posicionado_antes = False
            return

        # saiu neste candle (stop/alvo executado pela corretora ou fechamento por sinal contrário)?
        saiu_neste_candle = self._posicionado_antes and posicao is None
        sinal = int(self.estrategia.sinais_limpos(df).iloc[-1])
        if posicao is not None and cfg.backtest.sair_sinal_contrario and sinal == -posicao.direcao:
            self.log.info("Sinal contrário: encerrando posição.")
            self.corretora.fechar_posicao(cfg.ativo, "sinal_contrario")
            posicao = None
            saiu_neste_candle = True
            if self._trava_diaria_atingida(ultimo, None):  # a saída pode ter estourado a perda diária
                self._posicionado_antes = False
                return

        if not proximo_operavel:  # fechar_fim_dia desligado: posição pode ficar aberta, mas não há entradas fora da janela
            self._posicionado_antes = posicao is not None
            return

        enviou_ordem = False
        um_por_vez = cfg.execucao.um_trade_por_vez
        if um_por_vez and posicao is None and sinal != 0 and saiu_neste_candle:
            self.log.info("Um trade por vez: saída neste candle; nova entrada só a partir do próximo candle.")
            sinal = 0
        if um_por_vez and posicao is None and sinal != 0 and getattr(self.corretora, "ha_posicao_ou_ordem", lambda _a: False)(cfg.ativo):
            self.log.info("Um trade por vez: há posição/ordem no ativo (de outra origem); aguardando zerar.")
            sinal = 0

        if posicao is None and sinal != 0:
            preco_ref = float(df["fechamento"].iloc[-1])
            obter_preco = getattr(self.corretora, "preco_referencia", None)
            if obter_preco is not None:  # usa o preço negociável atual (ask/bid) para ancorar stop/alvo
                try:
                    preco_ref = float(obter_preco(cfg.ativo, sinal)) or preco_ref
                except Exception:
                    pass
            stop, alvo = self.estrategia.calcular_stop_alvo(df, sinal, preco_ref)
            minimo = self.distancia_minima_stop
            if minimo and (abs(preco_ref - stop) < minimo or abs(alvo - preco_ref) < minimo):
                self.log.info(f"Sinal descartado: stop ({abs(preco_ref - stop):.0f} pts) ou alvo ({abs(alvo - preco_ref):.0f} pts) "
                              f"abaixo da distância mínima da plataforma ({minimo:.0f} pts).")
                self._posicionado_antes = False
                return
            if self.filtro_ia is not None and self.filtro_ia.modelo is not None:
                prob = self.filtro_ia.probabilidade(df, len(df) - 1, sinal)
                if prob < self.filtro_ia.limiar:
                    self.log.info(f"Sinal {'COMPRA' if sinal == 1 else 'VENDA'} vetado pela IA (p={prob:.2f} < {self.filtro_ia.limiar:.2f}).")
                    self._posicionado_antes = False
                    return
                self.log.info(f"IA aprovou o sinal (p={prob:.2f} ≥ {self.filtro_ia.limiar:.2f}).")
            self.log.info(f"Sinal {'COMPRA' if sinal == 1 else 'VENDA'} em {ultimo} | ref={preco_ref:.2f} "
                          f"stop={stop:.2f} alvo={alvo:.2f}")
            enviou_ordem = self.corretora.enviar_ordem(cfg.ativo, sinal, cfg.contratos, stop, alvo, self.estrategia.nome)
        elif posicao is None:
            self.log.info(f"{ultimo} | sem sinal | fechamento {float(candle['fechamento']):.2f}")
        self._posicionado_antes = posicao is not None or enviou_ordem

    def _resolver_distancia_minima(self) -> float:
        configurada = self.cfg.execucao.distancia_minima_stop_pontos
        if configurada > 0:
            return float(configurada)
        obter = getattr(self.corretora, "distancia_minima_stop", None)
        try:
            return float(obter(self.cfg.ativo)) if obter else 0.0
        except Exception as erro:
            self.log.warning(f"Não foi possível ler a distância mínima de stop do MT5: {erro}")
            return 0.0

    def _trava_diaria_atingida(self, ultimo: pd.Timestamp, posicao) -> bool:
        """Mesma regra do backtest: sem novas entradas no dia após atingir a perda máxima diária."""
        limite = self.cfg.execucao.perda_maxima_diaria
        if limite <= 0:
            return False
        lucro_dia = self.corretora.lucro_do_dia(self.cfg.ativo, ultimo)
        if lucro_dia > -abs(limite):
            return False
        if self._bloqueado_no_dia != ultimo.normalize():
            self._bloqueado_no_dia = ultimo.normalize()
            self.log.warning(f"Perda máxima diária atingida ({lucro_dia:.2f}). Sem novas entradas hoje.")
        if posicao is not None:
            self.corretora.fechar_posicao(self.cfg.ativo, "perda_maxima_diaria")
        return True

    def parar(self) -> None:
        """Solicita o encerramento do laço (usado pela interface gráfica)."""
        self.ativo = False

    def _aguardar(self, segundos: float) -> None:
        fim = time.time() + segundos
        while self.ativo and time.time() < fim:
            time.sleep(min(0.25, max(0.0, fim - time.time())))

    def _resumo_simulado(self) -> None:
        historico = getattr(self.corretora, "historico", None)
        if not historico:
            return
        total = sum(h["resultado"] for h in historico)
        ganhos = sum(1 for h in historico if h["resultado"] > 0)
        self.log.info(f"Resumo simulado: {len(historico)} trades | acerto {ganhos / len(historico):.0%} | "
                      f"resultado {total:+.2f} | saldo final {self.corretora.saldo:.2f}")

    def _reavaliar_se_preciso(self) -> None:
        horas = self.cfg.execucao.reavaliar_a_cada_horas
        if not horas or self.reavaliador is None:
            return
        if (datetime.now() - self._ultima_reavaliacao).total_seconds() < horas * 3600:
            return
        self._ultima_reavaliacao = datetime.now()
        if self.corretora.obter_posicao(self.cfg.ativo) is not None:
            return  # reavalia apenas quando estiver zerado
        self.log.info("Reavaliando estratégias com dados recentes...")
        nova = self.reavaliador()
        if nova is not None and nova.nome != self.estrategia.nome:
            self.log.info(f"Estratégia trocada: {self.estrategia.nome} -> {nova.nome}")
            self.estrategia = nova
