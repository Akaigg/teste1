"""Interface de linha de comando (subcomandos) — alternativa ao menu interativo."""
from __future__ import annotations

import argparse

from aplicacao import servicos
from config.configuracao import Configuracao
from interface import apresentacao as ap
from interface import menu


def construir_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="robo_mt5", description="Robô de trading MT5 com seleção automática de estratégias.")
    p.add_argument("--ativo", help="símbolo (sobrescreve a configuração)")
    p.add_argument("--timeframe", help="M1, M5, M15, M30, H1, H4, D1")
    p.add_argument("--contratos", type=int)
    p.add_argument("--fonte", choices=["mt5", "csv", "sintetico"], help="fonte de dados")
    p.add_argument("--csv", help="caminho do CSV (fonte csv)")
    p.add_argument("--barras", type=int, help="candles de histórico")
    sub = p.add_subparsers(dest="comando")
    sub.add_parser("gui", help="abre a interface gráfica (padrão)")
    sub.add_parser("menu", help="abre o menu interativo no terminal")
    sub.add_parser("configurar", help="assistente de configuração")
    sub.add_parser("backtest", help="avalia todas as estratégias e gera o ranking")
    r = sub.add_parser("ranking", help="mostra o ranking salvo")
    r.add_argument("--top", type=int, default=20)
    d = sub.add_parser("detalhes", help="detalhes de uma estratégia do ranking")
    d.add_argument("estrategia", help="nome ou posição")
    sub.add_parser("listar", help="lista as estratégias disponíveis")
    o = sub.add_parser("operar", help="inicia a operação automática")
    o.add_argument("--real", action="store_true", help="envia ordens reais (padrão: simulado)")
    o.add_argument("--estrategia", help="força uma estratégia do ranking pelo nome")
    w = sub.add_parser("walkforward", help="análise walk-forward (consistência fora da amostra) de uma estratégia")
    w.add_argument("--estrategia", help="nome da estratégia (padrão: a melhor do ranking salvo)")
    w.add_argument("--top", type=int, default=0, help="compara as N melhores do ranking em vez de uma só")
    w.add_argument("--janelas", type=int, help="número de janelas de teste")
    w.add_argument("--treino", type=float, help="fração de cada janela usada como treino (ex.: 0.7)")
    w.add_argument("--ancorado", action="store_true", help="treino cresce desde o início dos dados")
    sub.add_parser("conexao", help="verifica conexão com o MT5")
    sb = sub.add_parser("simbolos", help="lista símbolos disponíveis na corretora (ex.: simbolos WIN)")
    sb.add_argument("filtro", nargs="?", default="WIN", help="texto contido no nome (padrão: WIN)")
    return p


def aplicar_sobrescritas(cfg: Configuracao, args) -> None:
    if args.ativo:
        cfg.ativo = args.ativo
    if args.timeframe:
        cfg.timeframe = args.timeframe.upper()
    if args.contratos:
        cfg.contratos = args.contratos
    if args.fonte:
        cfg.fonte_dados = args.fonte
    if args.csv:
        cfg.arquivo_csv = args.csv
        cfg.fonte_dados = "csv"
    if args.barras:
        cfg.barras_historico = args.barras


def executar(argv=None) -> None:
    args = construir_parser().parse_args(argv)
    cfg = Configuracao.carregar()
    aplicar_sobrescritas(cfg, args)
    comando = args.comando or "gui"

    if comando == "gui":
        try:
            from interface.janela import iniciar_interface
        except ImportError as erro:
            ap.imprimir(f"Interface gráfica indisponível ({erro}); abrindo o menu de terminal.", "yellow")
            menu.executar_menu(cfg)
            return
        iniciar_interface(cfg)
    elif comando == "menu":
        menu.executar_menu(cfg)
    elif comando == "configurar":
        menu.configurar(cfg)
    elif comando == "backtest":
        menu.executar_backtest(cfg)
    elif comando == "ranking":
        dados = servicos.carregar_ranking(cfg)
        if not dados:
            ap.imprimir("Nenhum ranking salvo. Rode: python main.py backtest", "yellow")
        else:
            ap.mostrar_ranking(dados["ranking"], args.top)
    elif comando == "detalhes":
        import builtins
        builtins_input = builtins.input
        builtins.input = lambda _="": args.estrategia  # reaproveita a função do menu
        try:
            menu.detalhes_estrategia(cfg)
        finally:
            builtins.input = builtins_input
    elif comando == "listar":
        menu.listar_estrategias()
    elif comando == "operar":
        if args.real:
            cfg.execucao.modo = "real"
        if args.estrategia:
            dados = servicos.carregar_ranking(cfg)
            entrada = next((r for r in (dados or {}).get("ranking", []) if r["nome"] == args.estrategia), None)
            if entrada is None:
                ap.imprimir("Estratégia não encontrada no ranking salvo.", "red")
                return
            estrategia = servicos.instanciar_do_ranking(entrada)
            df = servicos.carregar_dados(cfg) if cfg.ia.ativar else None
            servicos.montar_executor(cfg, estrategia, df).iniciar()
        else:
            menu.iniciar_operacao(cfg)
    elif comando == "walkforward":
        if args.janelas:
            cfg.walkforward.n_janelas = args.janelas
        if args.treino:
            cfg.walkforward.proporcao_treino = args.treino
        if args.ancorado:
            cfg.walkforward.ancorado = True
        menu.executar_walkforward(cfg, args.estrategia or "", args.top)
    elif comando == "conexao":
        menu.verificar_conexao(cfg)
    elif comando == "simbolos":
        menu.procurar_simbolos(cfg, args.filtro)
