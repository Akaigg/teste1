"""Menu interativo do terminal."""
from __future__ import annotations

from aplicacao import servicos
from config.configuracao import Configuracao
from dominio.estrategias.catalogo import construir_catalogo, familias
from infraestrutura.mt5_adaptador import MT5_DISPONIVEL, ErroMT5
from interface import apresentacao as ap


def _perguntar(texto: str, atual, tipo=str):
    resposta = input(f"{texto} [{atual}]: ").strip()
    if resposta == "":
        return atual
    if tipo is bool:
        return resposta.lower() in ("s", "sim", "y", "1", "true")
    try:
        return tipo(resposta.replace(",", "."))
    except ValueError:
        ap.imprimir("Valor inválido, mantido o anterior.", "yellow")
        return atual


def configurar(cfg: Configuracao) -> None:
    ap.titulo("Configuração")
    cfg.ativo = _perguntar("Ativo (nome exato no MT5)", cfg.ativo)
    cfg.timeframe = _perguntar("Timeframe (M1, M5, M15, M30, H1, H4, D1)", cfg.timeframe).upper()
    cfg.contratos = _perguntar("Contratos por operação", cfg.contratos, int)
    cfg.fonte_dados = _perguntar("Fonte de dados (mt5 / csv / sintetico)", cfg.fonte_dados).lower()
    if cfg.fonte_dados == "csv":
        cfg.arquivo_csv = _perguntar("Caminho do CSV", cfg.arquivo_csv)
    cfg.barras_historico = _perguntar("Candles de histórico para backtest", cfg.barras_historico, int)
    cfg.valor_ponto = _perguntar("Valor financeiro de 1 ponto por contrato", cfg.valor_ponto, float)
    cfg.custo_pontos_por_operacao = _perguntar("Custo por operação (em pontos)", cfg.custo_pontos_por_operacao, float)
    cfg.deslizamento_pontos = _perguntar("Deslizamento estimado (pontos)", cfg.deslizamento_pontos, float)
    cfg.capital_inicial = _perguntar("Capital inicial (para métricas)", cfg.capital_inicial, float)
    cfg.execucao.perda_maxima_diaria = _perguntar("Perda máxima diária (0 = desativado)", cfg.execucao.perda_maxima_diaria, float)
    cfg.execucao.horario_inicio = _perguntar("Horário de início (HH:MM)", cfg.execucao.horario_inicio)
    cfg.execucao.horario_fim = _perguntar("Horário de fim (HH:MM)", cfg.execucao.horario_fim)
    cfg.backtest.fechar_fim_dia = _perguntar("Encerrar posições no fim do dia? (s/n)", "s" if cfg.backtest.fechar_fim_dia else "n", bool)
    cfg.execucao.um_trade_por_vez = _perguntar("Um trade por vez (aguarda zerar antes de nova entrada)? (s/n)", "s" if cfg.execucao.um_trade_por_vez else "n", bool)
    cfg.execucao.distancia_minima_stop_pontos = _perguntar("Distância mínima de stop/alvo em pontos (0 = ler do MT5)", cfg.execucao.distancia_minima_stop_pontos, float)
    cfg.ia.ativar = _perguntar("Ativar filtro de IA? (s/n)", "s" if cfg.ia.ativar else "n", bool)
    cfg.salvar()
    ap.imprimir("Configuração salva em configuracao.json", "green")


def executar_backtest(cfg: Configuracao) -> None:
    ap.titulo("Backtest de todas as estratégias")
    try:
        ap.imprimir("Carregando dados...")
        df = servicos.carregar_dados(cfg)
        ap.imprimir(f"{len(df)} candles de {df.index[0]} a {df.index[-1]}")
        n = len(construir_catalogo())
        combos = len(cfg.backtest.grade_stop_atr) * len(cfg.backtest.grade_alvo_atr)
        ap.imprimir(f"Avaliando {n} estratégias x {combos} combinações de stop/alvo (treino) + validação...")
        ranking, caminho = servicos.gerar_ranking(cfg, df, ap.progresso_terminal)
        ap.mostrar_ranking(ranking)
        ap.imprimir(f"\nRanking salvo em {caminho}", "green")
        topo = ranking[0]
        if topo["pontuacao_final"] > 0:
            ap.imprimir(f"Estratégia selecionada automaticamente: {topo['nome']} "
                        f"(stop {topo['mult_stop']}xATR, alvo {topo['mult_alvo']}xATR)", "bold green")
        else:
            ap.imprimir("Nenhuma estratégia atingiu consistência mínima nestes dados.", "yellow")
        dados = servicos.carregar_ranking(cfg)
        if dados and dados["dados"].get("diagnostico"):
            ap.imprimir(servicos.texto_diagnostico(dados["dados"]["diagnostico"]), "yellow" if topo["pontuacao_final"] <= 0 else "dim")
    except (ErroMT5, ValueError) as erro:
        ap.imprimir(f"Erro: {erro}", "red")


def ver_ranking(cfg: Configuracao) -> None:
    dados = servicos.carregar_ranking(cfg)
    if not dados:
        ap.imprimir("Nenhum ranking salvo para este ativo/timeframe. Execute o backtest primeiro.", "yellow")
        return
    ap.imprimir(f"Ranking gerado em {dados['gerado_em']} com {dados['dados']['barras']} candles "
                f"({dados['dados']['inicio']} a {dados['dados']['fim']})")
    limite = _perguntar("Quantas estratégias mostrar", 20, int)
    ap.mostrar_ranking(dados["ranking"], limite)


def detalhes_estrategia(cfg: Configuracao) -> None:
    dados = servicos.carregar_ranking(cfg)
    if not dados:
        ap.imprimir("Execute o backtest primeiro.", "yellow")
        return
    entrada = input("Posição no ranking ou nome da estratégia: ").strip()
    escolhida = None
    for r in dados["ranking"]:
        if entrada == str(r["posicao"]) or entrada == r["nome"]:
            escolhida = r
            break
    if escolhida is None:
        ap.imprimir("Estratégia não encontrada.", "red")
        return
    ap.titulo(f"{escolhida['nome']}  ({escolhida['familia']})")
    ap.imprimir(escolhida["descricao"])
    ap.imprimir(f"Parâmetros: {escolhida['parametros']} | stop {escolhida['mult_stop']}xATR | alvo {escolhida['mult_alvo']}xATR")
    ap.imprimir(f"Nota final {escolhida['pontuacao_final']} (treino {escolhida['pontuacao_treino']}, validação {escolhida['pontuacao_validacao']})")
    ap.imprimir(f"Consistência treino: {escolhida.get('consistencia_treino')}")
    ap.imprimir(f"Consistência validação: {escolhida.get('consistencia_validacao')}")
    ap.mostrar_metricas(escolhida["metricas_treino"], "Treino")
    ap.mostrar_metricas(escolhida["metricas_validacao"], "Validação (fora da amostra)")
    ap.mostrar_metricas(escolhida["metricas_total"], "Período completo")


def listar_estrategias() -> None:
    ap.titulo("Estratégias disponíveis")
    linhas = [[i, e.nome, e.familia, e.descricao] for i, e in enumerate(construir_catalogo(), 1)]
    ap.tabela(["#", "Nome", "Família", "Descrição"], linhas)
    ap.imprimir(f"Total: {len(linhas)} estratégias | por família: {familias()}")


def iniciar_operacao(cfg: Configuracao) -> None:
    ap.titulo(f"Operação automática — modo {cfg.execucao.modo.upper()}")
    estrategia = servicos.melhor_estrategia(cfg)
    if estrategia is None:
        ap.imprimir("Nenhuma estratégia elegível no ranking. Execute o backtest primeiro.", "yellow")
        return
    ap.imprimir(f"Estratégia: {estrategia.nome} | stop {estrategia.mult_stop}xATR | alvo {estrategia.mult_alvo}xATR | "
                f"contratos {cfg.contratos}")
    if cfg.execucao.modo == "real":
        ap.imprimir("ATENÇÃO: ordens REAIS serão enviadas para a conta logada no MT5.", "bold red")
        if input("Digite CONFIRMO para prosseguir: ").strip() != "CONFIRMO":
            ap.imprimir("Cancelado.")
            return
    try:
        df = servicos.carregar_dados(cfg) if cfg.ia.ativar else None
        executor = servicos.montar_executor(cfg, estrategia, df)
        executor.iniciar()
    except (ErroMT5, ValueError) as erro:
        ap.imprimir(f"Erro: {erro}", "red")


def alternar_modo(cfg: Configuracao) -> None:
    cfg.execucao.modo = "real" if cfg.execucao.modo == "simulado" else "simulado"
    cfg.salvar()
    ap.imprimir(f"Modo agora é {cfg.execucao.modo.upper()}", "bold")


def verificar_conexao(cfg: Configuracao) -> None:
    ap.titulo("Conexão MT5")
    if not MT5_DISPONIVEL:
        ap.imprimir("Pacote MetaTrader5 não disponível neste sistema (somente Windows: pip install MetaTrader5).", "yellow")
        return
    try:
        mt5 = servicos.obter_mt5(cfg)
        ap.imprimir(mt5.obter_conta().descrever(), "green")
        if cfg.ativo:
            df = mt5.obter_candles(cfg.ativo, cfg.timeframe, 5)
            ap.imprimir(f"Último candle de {cfg.ativo} {cfg.timeframe}: {df.index[-1]} fechamento {df['fechamento'].iloc[-1]}")
    except ErroMT5 as erro:
        ap.imprimir(f"Erro: {erro}", "red")


def procurar_simbolos(cfg: Configuracao, filtro: str = "") -> None:
    ap.titulo("Símbolos disponíveis na corretora")
    if not MT5_DISPONIVEL:
        ap.imprimir("Pacote MetaTrader5 não disponível neste sistema.", "yellow")
        return
    if not filtro:
        filtro = input("Texto contido no nome (ex.: WIN): ").strip()
    try:
        simbolos = servicos.procurar_simbolos(cfg, filtro)
    except ErroMT5 as erro:
        ap.imprimir(f"Erro: {erro}", "red")
        return
    if not simbolos:
        ap.imprimir(f"Nenhum símbolo contendo '{filtro}'.", "yellow")
        return
    ap.tabela(["Nome", "Descrição", "No Observador", "Caminho"],
              [[s["nome"], s["descricao"], "sim" if s["visivel"] else "não", s["caminho"]] for s in simbolos])
    ap.imprimir("Copie o nome exato para o campo 'ativo'. Para o mini índice, prefira o contínuo (WIN$N, WIN$, WINFUT...) se existir.")


def executar_menu(cfg: Configuracao) -> None:
    opcoes = {
        "1": ("Configurar (ativo, timeframe, contratos, fonte de dados, custos...)", configurar),
        "2": ("Rodar backtest de TODAS as estratégias e gerar ranking", executar_backtest),
        "3": ("Ver ranking salvo", ver_ranking),
        "4": ("Ver detalhes de uma estratégia do ranking", detalhes_estrategia),
        "5": ("Listar estratégias disponíveis", lambda c: listar_estrategias()),
        "6": ("Iniciar operação automática com a melhor estratégia", iniciar_operacao),
        "7": ("Alternar modo simulado / real", alternar_modo),
        "8": ("Verificar conexão e conta do MT5", verificar_conexao),
        "9": ("Procurar símbolos disponíveis na corretora", lambda c: procurar_simbolos(c)),
    }
    while True:
        ap.titulo("ROBÔ MT5 — Seleção automática de estratégias")
        ap.imprimir(cfg.resumo(), "dim")
        for k, (texto, _) in opcoes.items():
            ap.imprimir(f"  {k}) {texto}")
        ap.imprimir("  0) Sair")
        escolha = input("\nEscolha: ").strip()
        if escolha == "0":
            break
        if escolha in opcoes:
            opcoes[escolha][1](cfg)
        else:
            ap.imprimir("Opção inválida.", "yellow")
