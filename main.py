"""
Ponto de entrada do Robô MT5.

    python main.py                 -> interface gráfica
    python main.py menu            -> menu interativo no terminal
    python main.py backtest        -> avalia todas as estratégias e gera o ranking
    python main.py ranking         -> mostra o ranking salvo
    python main.py walkforward     -> análise walk-forward
    python main.py operar          -> opera em modo simulado com a melhor estratégia
    python main.py operar --real   -> envia ordens reais na conta logada no MT5
    python main.py --help          -> todas as opções

Como executável (RoboMT5.exe, gerado por `python empacotar.py`): dê dois
cliques para abrir a interface gráfica; os mesmos subcomandos funcionam
pelo terminal (RoboMT5.exe backtest ...), mas sem console próprio.
"""
import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def _garantir_saida_texto() -> None:
    """Executável em modo janela não tem console: a saída dos subcomandos vai para registros/terminal_<data>.txt."""
    if sys.stdout is not None and sys.stderr is not None:
        return
    from datetime import datetime
    from config.caminhos import caminho
    pasta = caminho("registros")
    os.makedirs(pasta, exist_ok=True)
    arquivo = open(os.path.join(pasta, f"terminal_{datetime.now():%Y%m%d}.txt"), "a", encoding="utf-8", buffering=1)
    if sys.stdout is None:
        sys.stdout = arquivo
    if sys.stderr is None:
        sys.stderr = arquivo


_garantir_saida_texto()

from interface.comandos import executar  # noqa: E402


def _mostrar_erro_fatal(texto: str) -> None:
    """No executável em modo janela não há console: mostra o erro numa caixa de diálogo."""
    try:
        import tkinter as tk
        from tkinter import messagebox
        raiz = tk.Tk()
        raiz.withdraw()
        messagebox.showerror("Robô MT5 — erro", texto)
        raiz.destroy()
    except Exception:
        pass


if __name__ == "__main__":
    if getattr(sys, "frozen", False):
        try:
            executar()
        except SystemExit:
            raise
        except Exception:
            erro = traceback.format_exc()
            try:
                from infraestrutura.registro import obter_registrador
                obter_registrador().error(erro)
            except Exception:
                pass
            _mostrar_erro_fatal(erro[-2500:])
            sys.exit(1)
    else:
        executar()
