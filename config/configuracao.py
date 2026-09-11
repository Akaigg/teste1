"""
Configuração central do robô.

Toda configuração fica em um único arquivo JSON (configuracao.json) que pode
ser editado manualmente ou pelo menu interativo. As dataclasses abaixo
documentam cada campo e fornecem valores padrão genéricos (nenhum valor é
moldado para um ativo específico).
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, asdict
from typing import List

CAMINHO_PADRAO = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "configuracao.json")


@dataclass
class ConfiguracaoBacktest:
    fechar_fim_dia: bool = True            # encerra posições no último candle do dia
    sair_sinal_contrario: bool = True      # sai da posição quando surge sinal oposto
    max_barras_posicao: int = 0            # 0 = sem limite de tempo em posição
    proporcao_treino: float = 0.7          # parcela dos dados usada para ajustar stop/alvo
    n_janelas: int = 6                     # janelas temporais para medir consistência
    min_trades: int = 30                   # mínimo de trades no treino para a estratégia ser elegível
    grade_stop_atr: List[float] = field(default_factory=lambda: [1.0, 1.5, 2.0, 3.0])
    grade_alvo_atr: List[float] = field(default_factory=lambda: [1.0, 1.5, 2.0, 3.0, 4.0])
    peso_validacao: float = 0.6            # peso da pontuação fora da amostra na nota final


@dataclass
class ConfiguracaoExecucao:
    modo: str = "simulado"                 # "simulado" (não envia ordens) ou "real"
    intervalo_segundos: int = 5            # intervalo entre verificações de novo candle
    perda_maxima_diaria: float = 0.0       # em moeda da conta; 0 = desativado
    horario_inicio: str = "09:05"
    horario_fim: str = "17:40"
    reavaliar_a_cada_horas: float = 0.0    # 0 = não reavalia estratégia durante a operação
    magic: int = 20260907                  # identificador das ordens do robô no MT5
    desvio_maximo_pontos: int = 10         # slippage máximo aceito em ordens a mercado
    um_trade_por_vez: bool = True          # só entra com o ativo totalmente zerado; após win/loss espera o próximo candle
    distancia_minima_stop_pontos: float = 0.0  # distância mínima de stop/alvo em pontos; 0 = usar o valor informado pelo MT5


@dataclass
class ConfiguracaoWalkForward:
    n_janelas: int = 6                     # quantidade de janelas fora da amostra (teste)
    proporcao_treino: float = 0.7          # fração de cada janela usada para otimizar stop/alvo (treino)
    ancorado: bool = False                 # True: o treino começa sempre no início dos dados (janela crescente)
    top_ranking: int = 10                  # quantas estratégias do ranking comparar no modo "lote"


@dataclass
class ConfiguracaoIA:
    ativar: bool = False                   # filtro de IA (RandomForest) que veta sinais de baixa probabilidade
    margem_probabilidade: float = 0.05     # veta se p(lucro) < ponto de equilíbrio da estratégia + margem
    min_trades_treino: int = 60


@dataclass
class Configuracao:
    ativo: str = ""                        # símbolo exatamente como aparece no MT5
    timeframe: str = "M5"                  # M1, M5, M15, M30, H1, H4, D1
    contratos: int = 1
    barras_historico: int = 20000          # candles usados no backtest
    fonte_dados: str = "mt5"               # "mt5", "csv" ou "sintetico"
    arquivo_csv: str = ""
    caminho_terminal_mt5: str = ""         # opcional: caminho do terminal64.exe
    valor_ponto: float = 1.0               # valor financeiro de 1 ponto por contrato
    custo_pontos_por_operacao: float = 0.0 # custos (corretagem/emolumentos) convertidos em pontos por trade
    deslizamento_pontos: float = 0.0       # slippage estimado em pontos por execução a mercado
    capital_inicial: float = 10000.0
    backtest: ConfiguracaoBacktest = field(default_factory=ConfiguracaoBacktest)
    execucao: ConfiguracaoExecucao = field(default_factory=ConfiguracaoExecucao)
    ia: ConfiguracaoIA = field(default_factory=ConfiguracaoIA)
    walkforward: ConfiguracaoWalkForward = field(default_factory=ConfiguracaoWalkForward)

    # ------------------------------------------------------------------ util
    def para_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def de_dict(cls, dados: dict) -> "Configuracao":
        cfg = cls()
        for chave, valor in dados.items():
            if chave == "backtest":
                cfg.backtest = ConfiguracaoBacktest(**{k: v for k, v in valor.items() if k in ConfiguracaoBacktest.__dataclass_fields__})
            elif chave == "execucao":
                cfg.execucao = ConfiguracaoExecucao(**{k: v for k, v in valor.items() if k in ConfiguracaoExecucao.__dataclass_fields__})
            elif chave == "ia":
                valor = dict(valor)
                valor.pop("limiar_probabilidade", None)  # campo antigo (limiar absoluto), substituído pela margem
                cfg.ia = ConfiguracaoIA(**{k: v for k, v in valor.items() if k in ConfiguracaoIA.__dataclass_fields__})
            elif chave == "walkforward":
                cfg.walkforward = ConfiguracaoWalkForward(**{k: v for k, v in valor.items()
                                                             if k in ConfiguracaoWalkForward.__dataclass_fields__})
            elif chave in cls.__dataclass_fields__:
                setattr(cfg, chave, valor)
        return cfg

    def salvar(self, caminho: str = CAMINHO_PADRAO) -> None:
        with open(caminho, "w", encoding="utf-8") as arq:
            json.dump(self.para_dict(), arq, indent=2, ensure_ascii=False)

    @classmethod
    def carregar(cls, caminho: str = CAMINHO_PADRAO) -> "Configuracao":
        if not os.path.exists(caminho):
            cfg = cls()
            cfg.salvar(caminho)
            return cfg
        with open(caminho, "r", encoding="utf-8") as arq:
            return cls.de_dict(json.load(arq))

    def resumo(self) -> str:
        return (f"Ativo: {self.ativo or '(não definido)'} | Timeframe: {self.timeframe} | "
                f"Contratos: {self.contratos} | Fonte: {self.fonte_dados} | Modo: {self.execucao.modo} | "
                f"IA: {'ligada' if self.ia.ativar else 'desligada'}")
