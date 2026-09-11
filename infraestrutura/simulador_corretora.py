"""
Corretora simulada (paper trading): executa ordens em memória usando os
próprios candles recebidos pelo executor. Nenhuma ordem vai ao MT5.

Fidelidade ao MT5: uma ordem a mercado enviada no fechamento do candle N é
preenchida na ABERTURA do candle N+1 (mais deslizamento), e stop/alvo são
re-ancorados ao preço de preenchimento mantendo as distâncias calculadas,
exatamente como o SL/TP baseado em ask/bid no momento do envio.
"""
from __future__ import annotations

from typing import List, Optional

import pandas as pd

from dominio.modelos import InformacoesConta, Posicao


class SimuladorCorretora:
    def __init__(self, saldo_inicial: float, valor_ponto: float, registrador=None, deslizamento: float = 0.0,
                 custo_pontos: float = 0.0, distancia_minima_stop: float = 0.0):
        self.saldo = saldo_inicial
        self.distancia_minima = distancia_minima_stop
        self.valor_ponto = valor_ponto
        self.registrador = registrador
        self.deslizamento = deslizamento
        self.custo_pontos = custo_pontos
        self.posicao: Optional[Posicao] = None
        self._ordem_pendente: Optional[dict] = None
        self.historico: List[dict] = []
        self._preco_atual: float = 0.0
        self._tempo_atual: Optional[pd.Timestamp] = None
        self._proximo_ticket = 1

    # ---- alimentação de preços pelo executor
    def atualizar(self, candle: pd.Series, tempo: pd.Timestamp) -> None:
        if tempo == self._tempo_atual:
            return
        self._tempo_atual = tempo
        if self._ordem_pendente is not None and self.posicao is None:
            self._preencher(self._ordem_pendente, float(candle["abertura"]), tempo)
        self._ordem_pendente = None
        self._preco_atual = float(candle["fechamento"])
        p = self.posicao
        if p is None:
            return
        if p.direcao == 1:
            if candle["minima"] <= p.stop:
                self._encerrar(p.stop - self.deslizamento, "stop")  # stop = ordem a mercado: sofre deslizamento
            elif candle["maxima"] >= p.alvo:
                self._encerrar(p.alvo, "alvo")
        else:
            if candle["maxima"] >= p.stop:
                self._encerrar(p.stop + self.deslizamento, "stop")
            elif candle["minima"] <= p.alvo:
                self._encerrar(p.alvo, "alvo")

    # ---- interface Corretora
    def obter_conta(self) -> InformacoesConta:
        return InformacoesConta(login=0, nome="SIMULADO", servidor="paper", saldo=self.saldo,
                                patrimonio=self.saldo, moeda="", alavancagem=0)

    def obter_posicao(self, ativo: str) -> Optional[Posicao]:
        return self.posicao

    def preco_referencia(self, ativo: str, direcao: int) -> float:
        return self._preco_atual

    def distancia_minima_stop(self, ativo: str) -> float:
        return self.distancia_minima

    def ha_posicao_ou_ordem(self, ativo: str) -> bool:
        """Qualquer posição ou ordem pendente no ativo (de qualquer origem)."""
        return self.posicao is not None or self._ordem_pendente is not None

    def enviar_ordem(self, ativo, direcao, contratos, stop, alvo, comentario="") -> bool:
        if self.posicao is not None or self._ordem_pendente is not None:
            return False
        referencia = self._preco_atual
        if self.distancia_minima and (abs(referencia - stop) < self.distancia_minima or abs(alvo - referencia) < self.distancia_minima):
            if self.registrador:
                self.registrador.warning(f"[SIMULADO] Ordem rejeitada: stop/alvo abaixo da distância mínima de {self.distancia_minima:.0f} pontos.")
            return False
        self._ordem_pendente = {"ativo": ativo, "direcao": direcao, "contratos": contratos,
                                "dist_stop": stop - referencia, "dist_alvo": alvo - referencia, "comentario": comentario}
        if self.registrador:
            self.registrador.info(f"[SIMULADO] Ordem {'COMPRA' if direcao == 1 else 'VENDA'} {contratos} {ativo} enviada "
                                  f"(ref {referencia:.2f}); preenche na abertura do próximo candle. ({comentario})")
        return True

    def _preencher(self, ordem: dict, abertura: float, tempo: pd.Timestamp) -> None:
        d = ordem["direcao"]
        preco = abertura + d * self.deslizamento
        self.posicao = Posicao(ativo=ordem["ativo"], direcao=d, contratos=ordem["contratos"], preco_entrada=preco,
                               stop=preco + ordem["dist_stop"], alvo=preco + ordem["dist_alvo"],
                               ticket=self._proximo_ticket, data_abertura=tempo)
        self._proximo_ticket += 1
        if self.registrador:
            p = self.posicao
            self.registrador.info(f"[SIMULADO] {'COMPRA' if d == 1 else 'VENDA'} preenchida @ {preco:.2f} "
                                  f"stop={p.stop:.2f} alvo={p.alvo:.2f} em {tempo}")

    def fechar_posicao(self, ativo: str, motivo: str = "") -> bool:
        self._ordem_pendente = None
        if self.posicao is None:
            return False
        self._encerrar(self._preco_atual - self.posicao.direcao * self.deslizamento, motivo or "manual")
        return True

    def lucro_do_dia(self, ativo: str, dia=None) -> float:
        if dia is None and self._tempo_atual is None:
            return 0.0
        hoje = (dia if dia is not None else self._tempo_atual).normalize()
        return sum(h["resultado"] for h in self.historico if h["saida_em"].normalize() == hoje)

    def _encerrar(self, preco: float, motivo: str) -> None:
        p = self.posicao
        pontos = p.direcao * (preco - p.preco_entrada) - self.custo_pontos
        resultado = pontos * self.valor_ponto * p.contratos
        self.saldo += resultado
        self.historico.append({"ativo": p.ativo, "direcao": p.direcao, "entrada": p.preco_entrada, "saida": preco,
                               "pontos": pontos, "resultado": resultado, "motivo": motivo,
                               "entrada_em": p.data_abertura, "saida_em": self._tempo_atual})
        if self.registrador:
            self.registrador.info(f"[SIMULADO] Saída por {motivo} @ {preco:.2f} | resultado {resultado:+.2f} | saldo {self.saldo:.2f}")
        self.posicao = None
