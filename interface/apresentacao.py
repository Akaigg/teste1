"""Apresentação no terminal (usa `rich` se instalado; senão, texto simples)."""
from __future__ import annotations

import sys
from typing import List, Sequence

try:
    from rich.console import Console
    from rich.table import Table
    _console = Console()
    RICH = True
except ImportError:
    _console = None
    RICH = False


def imprimir(texto: str = "", estilo: str = "") -> None:
    if RICH:
        _console.print(texto, style=estilo or None, highlight=False)
    else:
        print(texto)


def titulo(texto: str) -> None:
    linha = "=" * max(40, len(texto) + 4)
    imprimir(f"\n{linha}\n  {texto}\n{linha}", "bold cyan")


def tabela(colunas: Sequence[str], linhas: List[Sequence], titulo_tabela: str = "") -> None:
    linhas = [[str(c) for c in l] for l in linhas]
    if RICH:
        t = Table(title=titulo_tabela or None, show_lines=False, header_style="bold magenta")
        for c in colunas:
            t.add_column(c)
        for l in linhas:
            t.add_row(*l)
        _console.print(t)
        return
    larguras = [max(len(str(c)), *(len(l[i]) for l in linhas)) if linhas else len(str(c)) for i, c in enumerate(colunas)]
    if titulo_tabela:
        print(f"\n{titulo_tabela}")
    print(" | ".join(str(c).ljust(larguras[i]) for i, c in enumerate(colunas)))
    print("-+-".join("-" * w for w in larguras))
    for l in linhas:
        print(" | ".join(l[i].ljust(larguras[i]) for i in range(len(colunas))))


def progresso_terminal(atual: int, total: int, nome: str) -> None:
    barra = int(30 * atual / total)
    sys.stdout.write(f"\r[{'#' * barra}{'.' * (30 - barra)}] {atual:>3}/{total} {nome[:40]:<40}")
    sys.stdout.flush()
    if atual == total:
        sys.stdout.write("\n")


def moeda(valor: float) -> str:
    return f"{valor:,.2f}"


def mostrar_ranking(ranking: List[dict], limite: int = 20) -> None:
    com_ia = any(r.get("ia_no_ranking") for r in ranking)
    linhas = []
    for r in ranking[:limite]:
        mt, mv = r.get("metricas_total", {}), r.get("metricas_validacao", {})
        linha = [r["posicao"], r["nome"], r["familia"], f"{r['pontuacao_final']:.1f}"]
        if com_ia:
            linha += [f"{r.get('pontuacao_final_sem_ia', r['pontuacao_final']):.1f}",
                      f"{r['pontuacao_final_com_ia']:.1f}" if r.get("ia_treinada") else "-",
                      f"{r.get('ia_vetos_validacao', 0)}/{r.get('ia_sinais_validacao', 0)}" if r.get("ia_treinada") else "-"]
        linha += [f"{r['pontuacao_treino']:.0f}/{r['pontuacao_validacao']:.0f}",
                  f"{r['mult_stop']}/{r['mult_alvo']}", mt.get("total_trades", 0),
                  f"{mt.get('taxa_acerto', 0):.0f}%", f"{mt.get('fator_lucro', 0):.2f}",
                  moeda(mt.get("lucro_liquido", 0)), moeda(mv.get("lucro_liquido", 0)),
                  moeda(mt.get("drawdown_maximo", 0))]
        linhas.append(linha)
    colunas = ["#", "Estratégia", "Família", "Nota"] + (["Sem IA", "Com IA", "Vetos"] if com_ia else []) + \
              ["Tr/Val", "Stop/Alvo", "Trades", "Acerto", "FL", "Lucro", "Lucro val.", "DD"]
    tabela(colunas, linhas, "Ranking por consistência (Nota 0-100 | Tr/Val = nota treino/validação | Stop/Alvo em múltiplos de ATR"
                            + (" | Vetos = sinais vetados pela IA / sinais na validação)" if com_ia else ")"))


def mostrar_metricas(m: dict, titulo_tabela: str) -> None:
    if not m:
        imprimir("(sem métricas)")
        return
    chaves = ["total_trades", "taxa_acerto", "lucro_liquido", "fator_lucro", "payoff", "expectativa",
              "drawdown_maximo", "drawdown_maximo_pct", "sharpe", "max_perdas_seguidas", "fator_recuperacao"]
    tabela(["Métrica", "Valor"], [[k, f"{m[k]:.2f}" if isinstance(m.get(k), float) else m.get(k, "-")] for k in chaves],
           titulo_tabela)
