"""
Ponto de entrada do Robô MT5.

    python main.py                 -> menu interativo
    python main.py backtest        -> avalia todas as estratégias e gera o ranking
    python main.py ranking         -> mostra o ranking salvo
    python main.py operar          -> opera em modo simulado com a melhor estratégia
    python main.py operar --real   -> envia ordens reais na conta logada no MT5
    python main.py --help          -> todas as opções
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from interface.comandos import executar  # noqa: E402

if __name__ == "__main__":
    executar()
