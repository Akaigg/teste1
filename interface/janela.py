"""
Interface gráfica desktop (Tkinter) do Robô MT5.

Cinco abas: Configuração, Backtest & Ranking, Operação, Walk-forward e Estratégias.
Tarefas demoradas (carregar dados, backtest, operação ao vivo) rodam em
threads; a comunicação com a janela é feita por uma fila processada com
`after()`, evitando travar a interface. Toda a lógica de negócio continua na
camada de aplicação (`aplicacao/servicos.py`).
"""
from __future__ import annotations

import logging
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText
from typing import Optional

from aplicacao import servicos
from config.configuracao import Configuracao
from dominio.estrategias.catalogo import construir_catalogo, familias
from infraestrutura.mt5_adaptador import MT5_DISPONIVEL, ErroMT5
from infraestrutura.registro import obter_registrador

TIMEFRAMES = ["M1", "M2", "M3", "M5", "M10", "M15", "M30", "H1", "H4", "D1"]
FONTES = ["mt5", "csv", "sintetico"]

COLUNAS_RANKING = [
    ("posicao", "#", 34), ("nome", "Estratégia", 200), ("familia", "Família", 90), ("nota", "Nota", 52),
    ("nota_sem_ia", "Sem IA", 55), ("nota_com_ia", "Com IA", 55), ("vetos_ia", "Vetos IA", 62),
    ("treino", "Treino", 52), ("valid", "Valid.", 52), ("stop", "Stop", 46), ("alvo", "Alvo", 46),
    ("trades", "Trades", 52), ("acerto", "Acerto", 55), ("fl", "F.Lucro", 58), ("lucro", "Lucro", 85),
    ("lucro_val", "Lucro val.", 85), ("dd", "DD máx", 80),
]

COLUNAS_JANELAS_WF = [
    ("numero", "#", 30), ("treino", "Treino (período)", 210), ("teste", "Teste (período)", 210), ("stop", "Stop", 44),
    ("alvo", "Alvo", 44), ("nota_treino", "Nota tr.", 58), ("nota_teste", "Nota teste", 68), ("trades", "Trades", 52),
    ("lucro", "Lucro teste", 90), ("fl", "F.Lucro", 58), ("dd", "DD", 80), ("acerto", "Acerto", 55), ("efic", "Efic.", 52),
    ("lucro_fixo", "Lucro c/ fixos", 95),
]

COLUNAS_COMPARACAO_WF = [
    ("posicao", "#", 30), ("nome", "Estratégia", 230), ("familia", "Família", 120), ("pontuacao", "Pont. WF", 62),
    ("veredito", "Veredito", 80), ("janelas", "Janelas +", 66), ("efic", "Efic.", 52), ("estab", "Estab.", 52),
    ("trades", "Trades", 52), ("lucro", "Lucro OOS", 90), ("fl", "F.Lucro", 58), ("dd", "DD", 80),
    ("lucro_fixo", "Lucro c/ fixos", 95), ("motivos", "Observações", 400),
]

CHAVES_METRICAS = [
    ("total_trades", "Trades"), ("taxa_acerto", "Taxa de acerto %"), ("lucro_liquido", "Lucro líquido"),
    ("fator_lucro", "Fator de lucro"), ("payoff", "Payoff"), ("expectativa", "Expectativa/trade"),
    ("drawdown_maximo", "Drawdown máximo"), ("drawdown_maximo_pct", "Drawdown máximo %"), ("sharpe", "Sharpe"),
    ("max_perdas_seguidas", "Máx. perdas seguidas"), ("fator_recuperacao", "Fator de recuperação"),
    ("sinais_descartados_stop_minimo", "Sinais descartados (stop mín.)"),
]


class ManipuladorLogFila(logging.Handler):
    """Encaminha registros do logger para a fila da interface."""

    def __init__(self, fila: queue.Queue):
        super().__init__()
        self.fila = fila
        self.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s", "%H:%M:%S"))

    def emit(self, record):
        self.fila.put(("log", self.format(record), record.levelno))


def _fmt(valor, casas=2):
    if isinstance(valor, float):
        return f"{valor:,.{casas}f}"
    return "-" if valor is None else str(valor)


# ====================================================================== aplicação
class Aplicativo:
    def __init__(self, cfg: Configuracao):
        self.cfg = cfg
        self.raiz = tk.Tk()
        self.raiz.title("Robô MT5 — seleção automática de estratégias")
        self.raiz.geometry("1280x800")
        self.raiz.minsize(1000, 650)
        self.fila: queue.Queue = queue.Queue()
        self.df = None
        self.ranking: list = []
        self.executor = None
        self.thread_executor: Optional[threading.Thread] = None
        self.ocupado = False
        self.campos: dict = {}

        self.log = obter_registrador()
        self.log.addHandler(ManipuladorLogFila(self.fila))

        self._estilo()
        self._construir()
        self._carregar_ranking_salvo(silencioso=True)
        self.raiz.after(150, self._processar_fila)
        self.raiz.after(3000, self._atualizar_status_operacao)
        self.raiz.protocol("WM_DELETE_WINDOW", self._fechar)

    # ------------------------------------------------------------------ visual
    def _estilo(self):
        estilo = ttk.Style(self.raiz)
        for tema in ("vista", "clam"):
            if tema in estilo.theme_names():
                estilo.theme_use(tema)
                break
        estilo.configure("Titulo.TLabel", font=("Segoe UI", 12, "bold"))
        estilo.configure("Status.TLabel", font=("Segoe UI", 10, "bold"))
        estilo.configure("Perigo.TButton", foreground="#b00020")
        estilo.configure("Treeview", rowheight=22)

    def _construir(self):
        topo = ttk.Frame(self.raiz, padding=(10, 8))
        topo.pack(fill="x")
        ttk.Label(topo, text="Robô MT5", style="Titulo.TLabel").pack(side="left")
        self.var_resumo = tk.StringVar(value=self.cfg.resumo())
        ttk.Label(topo, textvariable=self.var_resumo).pack(side="left", padx=20)

        self.abas = ttk.Notebook(self.raiz)
        self.abas.pack(fill="both", expand=True, padx=10, pady=(0, 6))
        self.aba_config = ttk.Frame(self.abas, padding=10)
        self.aba_backtest = ttk.Frame(self.abas, padding=10)
        self.aba_operacao = ttk.Frame(self.abas, padding=10)
        self.aba_walkforward = ttk.Frame(self.abas, padding=10)
        self.aba_estrategias = ttk.Frame(self.abas, padding=10)
        self.abas.add(self.aba_config, text="  1. Configuração  ")
        self.abas.add(self.aba_backtest, text="  2. Backtest & Ranking  ")
        self.abas.add(self.aba_operacao, text="  3. Operação  ")
        self.abas.add(self.aba_walkforward, text="  4. Walk-forward  ")
        self.abas.add(self.aba_estrategias, text="  Estratégias  ")
        self._construir_config()
        self._construir_backtest()
        self._construir_operacao()
        self._construir_walkforward()
        self._construir_estrategias()

        self.var_status = tk.StringVar(value="Pronto.")
        barra = ttk.Frame(self.raiz, padding=(10, 4))
        barra.pack(fill="x")
        ttk.Label(barra, textvariable=self.var_status).pack(side="left")
        self.progresso = ttk.Progressbar(barra, length=300, mode="determinate")
        self.progresso.pack(side="right")

    # ------------------------------------------------------------- aba configuração
    def _campo(self, pai, linha, rotulo, obj, atributo, tipo="str", opcoes=None, dica=""):
        ttk.Label(pai, text=rotulo).grid(row=linha, column=0, sticky="w", pady=2, padx=(0, 8))
        valor = getattr(obj, atributo)
        if tipo == "bool":
            var = tk.BooleanVar(value=bool(valor))
            widget = ttk.Checkbutton(pai, variable=var)
        elif tipo == "combo":
            var = tk.StringVar(value=str(valor))
            widget = ttk.Combobox(pai, textvariable=var, values=opcoes, state="readonly", width=14)
        else:
            texto = ", ".join(str(v) for v in valor) if tipo == "lista" else str(valor)
            var = tk.StringVar(value=texto)
            widget = ttk.Entry(pai, textvariable=var, width=18)
        widget.grid(row=linha, column=1, sticky="w")
        if dica:  # a dica aparece na barra de status quando o campo recebe foco ou o mouse
            widget.bind("<FocusIn>", lambda _e, d=dica, r=rotulo: self._definir_status(f"{r}: {d}"))
            widget.bind("<Enter>", lambda _e, d=dica, r=rotulo: self._definir_status(f"{r}: {d}"))
        self.campos[(id(obj), atributo)] = (obj, atributo, tipo, var)

    def _construir_config(self):
        a = self.aba_config
        cfg = self.cfg
        geral = ttk.LabelFrame(a, text="Geral", padding=10)
        bt = ttk.LabelFrame(a, text="Backtest / seleção", padding=10)
        ex = ttk.LabelFrame(a, text="Execução e IA", padding=10)
        geral.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        bt.grid(row=0, column=1, sticky="nsew", padx=8)
        ex.grid(row=0, column=2, sticky="nsew", padx=(8, 0))
        for c in range(3):
            a.columnconfigure(c, weight=1)

        self._campo(geral, 0, "Ativo", cfg, "ativo", dica="nome exato no MT5 — use 'Procurar símbolo' para listar os nomes da sua corretora")
        ttk.Button(geral, text="Procurar símbolo", command=self._procurar_simbolo, width=16).grid(row=0, column=2, sticky="w", padx=4)
        self._campo(geral, 1, "Timeframe", cfg, "timeframe", "combo", TIMEFRAMES)
        self._campo(geral, 2, "Contratos", cfg, "contratos", "int")
        self._campo(geral, 3, "Candles de histórico", cfg, "barras_historico", "int")
        self._campo(geral, 4, "Fonte de dados", cfg, "fonte_dados", "combo", FONTES)
        self._campo(geral, 5, "Arquivo CSV", cfg, "arquivo_csv")
        ttk.Button(geral, text="Procurar...", command=self._escolher_csv, width=10).grid(row=5, column=2, sticky="w", padx=4)
        self._campo(geral, 6, "Terminal MT5 (opcional)", cfg, "caminho_terminal_mt5", dica="caminho do terminal64.exe")
        self._campo(geral, 7, "Valor do ponto", cfg, "valor_ponto", "float", dica="R$ por ponto por contrato")
        self._campo(geral, 8, "Custo por operação (pts)", cfg, "custo_pontos_por_operacao", "float")
        self._campo(geral, 9, "Deslizamento (pts)", cfg, "deslizamento_pontos", "float")
        self._campo(geral, 10, "Capital inicial", cfg, "capital_inicial", "float")

        b = cfg.backtest
        self._campo(bt, 0, "Encerrar no fim do dia", b, "fechar_fim_dia", "bool")
        self._campo(bt, 1, "Sair em sinal contrário", b, "sair_sinal_contrario", "bool")
        self._campo(bt, 2, "Máx. barras em posição", b, "max_barras_posicao", "int", dica="0 = sem limite")
        self._campo(bt, 3, "Proporção de treino", b, "proporcao_treino", "float", dica="0.7 = 70% treino")
        self._campo(bt, 4, "Janelas de consistência", b, "n_janelas", "int")
        self._campo(bt, 5, "Mínimo de trades", b, "min_trades", "int")
        self._campo(bt, 6, "Grade stop (xATR)", b, "grade_stop_atr", "lista", dica="separe por vírgula")
        self._campo(bt, 7, "Grade alvo (xATR)", b, "grade_alvo_atr", "lista", dica="separe por vírgula")
        self._campo(bt, 8, "Peso da validação", b, "peso_validacao", "float", dica="0 a 1")

        e = cfg.execucao
        self._campo(ex, 0, "Modo", e, "modo", "combo", ["simulado", "real"])
        self._campo(ex, 1, "Intervalo (s)", e, "intervalo_segundos", "int")
        self._campo(ex, 2, "Perda máx. diária", e, "perda_maxima_diaria", "float", dica="0 = desativada")
        self._campo(ex, 3, "Horário início", e, "horario_inicio", dica="HH:MM")
        self._campo(ex, 4, "Horário fim", e, "horario_fim", dica="HH:MM")
        self._campo(ex, 5, "Reavaliar a cada (h)", e, "reavaliar_a_cada_horas", "float", dica="0 = nunca")
        self._campo(ex, 6, "Magic number", e, "magic", "int")
        self._campo(ex, 7, "Desvio máx. (pts)", e, "desvio_maximo_pontos", "int")
        self._campo(ex, 8, "Um trade por vez", e, "um_trade_por_vez", "bool",
                    dica="só entra com o ativo zerado (qualquer origem) e, após win/loss, espera o próximo candle; o backtest segue a mesma regra")
        self._campo(ex, 9, "Dist. mínima stop/alvo (pts)", e, "distancia_minima_stop_pontos", "float",
                    dica="0 = ler do MT5 (trade_stops_level); sinais com stop/alvo menores são descartados no backtest e ao vivo")
        ia = cfg.ia
        self._campo(ex, 10, "Ativar filtro de IA", ia, "ativar", "bool")
        self._campo(ex, 11, "Margem da IA", ia, "margem_probabilidade", "float",
                    dica="a IA veta o sinal quando a probabilidade prevista fica abaixo do ponto de equilíbrio da estratégia + esta margem")
        self._campo(ex, 12, "Mín. trades p/ treinar IA", ia, "min_trades_treino", "int")

        botoes = ttk.Frame(a)
        botoes.grid(row=1, column=0, columnspan=3, sticky="w", pady=12)
        ttk.Button(botoes, text="Salvar configuração", command=self._salvar_config).pack(side="left")
        ttk.Button(botoes, text="Testar conexão MT5", command=self._testar_mt5).pack(side="left", padx=8)
        ttk.Button(botoes, text="Recarregar do arquivo", command=self._recarregar_config).pack(side="left")
        self.var_conexao = tk.StringVar(value="")
        ttk.Label(botoes, textvariable=self.var_conexao, foreground="#0a6").pack(side="left", padx=12)
        ttk.Label(a, text="Passe o mouse sobre um campo para ver a explicação na barra de status. "
                          "Contratos e modo também podem ser alterados na aba Operação.",
                  foreground="#666").grid(row=2, column=0, columnspan=3, sticky="w")

    def _procurar_simbolo(self):
        if not self._aplicar_campos():
            return
        if not MT5_DISPONIVEL:
            messagebox.showwarning("MT5", "Pacote MetaTrader5 não disponível (somente Windows: pip install MetaTrader5).")
            return
        JanelaSimbolos(self)

    def _escolher_csv(self):
        caminho = filedialog.askopenfilename(filetypes=[("CSV", "*.csv"), ("Todos", "*.*")])
        if caminho:
            self.campos[(id(self.cfg), "arquivo_csv")][3].set(caminho)
            self.campos[(id(self.cfg), "fonte_dados")][3].set("csv")

    def _aplicar_campos(self) -> bool:
        try:
            for obj, atributo, tipo, var in self.campos.values():
                texto = var.get()
                if tipo == "bool":
                    valor = bool(texto)
                elif tipo == "int":
                    valor = int(float(str(texto).replace(",", ".")))
                elif tipo == "float":
                    valor = float(str(texto).replace(",", "."))
                elif tipo == "lista":
                    valor = [float(x) for x in str(texto).replace(";", ",").split(",") if x.strip()]
                else:
                    valor = str(texto).strip()
                    if atributo == "timeframe":
                        valor = valor.upper()
                setattr(obj, atributo, valor)
            self.var_resumo.set(self.cfg.resumo())
            return True
        except ValueError as erro:
            messagebox.showerror("Configuração", f"Valor inválido: {erro}")
            return False

    def _salvar_config(self):
        if self._aplicar_campos():
            self.cfg.salvar()
            self._definir_status("Configuração salva em configuracao.json")
            self._carregar_ranking_salvo(silencioso=True)

    def _recarregar_config(self):
        novo = Configuracao.carregar()
        for obj, atributo, tipo, var in self.campos.values():
            fonte = {id(self.cfg): novo, id(self.cfg.backtest): novo.backtest,
                     id(self.cfg.execucao): novo.execucao, id(self.cfg.ia): novo.ia}[id(obj)]
            valor = getattr(fonte, atributo)
            var.set(", ".join(str(v) for v in valor) if tipo == "lista" else valor)
        self._aplicar_campos()

    def _testar_mt5(self):
        if not self._aplicar_campos():
            return
        if not MT5_DISPONIVEL:
            messagebox.showwarning("MT5", "Pacote MetaTrader5 não disponível (somente Windows: pip install MetaTrader5).")
            return

        def tarefa():
            try:
                mt5 = servicos.obter_mt5(self.cfg)
                conta = mt5.obter_conta().descrever()
                extra = ""
                if self.cfg.ativo:
                    df = mt5.obter_candles(self.cfg.ativo, self.cfg.timeframe, 3)
                    extra = f" | último candle {df.index[-1]} = {df['fechamento'].iloc[-1]}"
                self.fila.put(("conexao", conta + extra))
            except ErroMT5 as erro:
                self.fila.put(("erro", str(erro)))
        threading.Thread(target=tarefa, daemon=True).start()

    # ------------------------------------------------------------- aba backtest
    def _construir_backtest(self):
        a = self.aba_backtest
        topo = ttk.Frame(a)
        topo.pack(fill="x")
        self.botao_backtest = ttk.Button(topo, text="▶ Rodar backtest de todas as estratégias", command=self._rodar_backtest)
        self.botao_backtest.pack(side="left")
        ttk.Button(topo, text="Carregar ranking salvo", command=self._carregar_ranking_salvo).pack(side="left", padx=8)
        ttk.Button(topo, text="Detalhes da selecionada", command=self._abrir_detalhes).pack(side="left")
        ttk.Button(topo, text="Usar na operação", command=self._usar_na_operacao).pack(side="left", padx=8)
        self.var_info_ranking = tk.StringVar(value="Nenhum ranking carregado.")
        ttk.Label(a, textvariable=self.var_info_ranking, foreground="#444", wraplength=1200, justify="left").pack(fill="x", pady=6)

        quadro = ttk.Frame(a)
        quadro.pack(fill="both", expand=True)
        self.arvore = ttk.Treeview(quadro, columns=[c[0] for c in COLUNAS_RANKING], show="headings", selectmode="browse")
        for chave, texto, largura in COLUNAS_RANKING:
            self.arvore.heading(chave, text=texto)
            self.arvore.column(chave, width=largura, minwidth=160 if chave == "nome" else 30,
                               anchor="center" if chave != "nome" else "w", stretch=chave == "nome")
        rolagem = ttk.Scrollbar(quadro, orient="vertical", command=self.arvore.yview)
        self.arvore.configure(yscrollcommand=rolagem.set)
        self.arvore.pack(side="left", fill="both", expand=True)
        rolagem.pack(side="right", fill="y")
        self.arvore.bind("<Double-1>", lambda _e: self._abrir_detalhes())
        self.arvore.tag_configure("topo", background="#e3f4e1")
        self.arvore.tag_configure("inelegivel", foreground="#999")

    def _rodar_backtest(self):
        if self.ocupado:
            return
        if not self._aplicar_campos():
            return
        if not self.cfg.ativo and self.cfg.fonte_dados == "mt5":
            messagebox.showwarning("Backtest", "Defina o ativo na aba Configuração.")
            return
        self.cfg.salvar()
        self._ocupar(True, "Carregando dados...")
        self.progresso["value"] = 0

        def tarefa():
            try:
                df = servicos.carregar_dados(self.cfg)
                self.fila.put(("status", f"{len(df)} candles de {df.index[0]} a {df.index[-1]}. Avaliando estratégias..."))
                ranking, caminho = servicos.gerar_ranking(
                    self.cfg, df, lambda k, t, nome: self.fila.put(("progresso", k, t, nome)))
                self.fila.put(("ranking", ranking, df, caminho))
            except Exception as erro:
                self.fila.put(("erro", f"Falha no backtest: {erro}"))
            finally:
                self.fila.put(("livre",))
        threading.Thread(target=tarefa, daemon=True).start()

    def _carregar_ranking_salvo(self, silencioso=False):
        dados = servicos.carregar_ranking(self.cfg)
        if not dados:
            if not silencioso:
                messagebox.showinfo("Ranking", "Nenhum ranking salvo para este ativo/timeframe. Rode o backtest.")
            self.ranking = []
            self._preencher_ranking([])
            self.var_info_ranking.set("Nenhum ranking carregado para este ativo/timeframe.")
            self._atualizar_lista_estrategias_operacao()
            return
        self.ranking = dados["ranking"]
        self._preencher_ranking(self.ranking)
        d = dados["dados"]
        self.var_info_ranking.set(f"Ranking de {dados['ativo']} {dados['timeframe']} gerado em {dados['gerado_em']} "
                                  f"| {d['barras']} candles ({d['inicio']} a {d['fim']})")
        self._atualizar_lista_estrategias_operacao()

    def _preencher_ranking(self, ranking):
        self.arvore.delete(*self.arvore.get_children())
        com_ia = any(r.get("ia_no_ranking") for r in ranking)
        for chave in ("nota_sem_ia", "nota_com_ia", "vetos_ia"):
            self.arvore.column(chave, width=58 if com_ia else 0, stretch=False, minwidth=0)
        for r in ranking:
            mt, mv = r.get("metricas_total", {}), r.get("metricas_validacao", {})
            treinada = r.get("ia_treinada")
            valores = [r["posicao"], r["nome"], r["familia"], _fmt(r["pontuacao_final"], 1),
                       _fmt(r.get("pontuacao_final_sem_ia", r["pontuacao_final"]), 1) if com_ia else "",
                       _fmt(r["pontuacao_final_com_ia"], 1) if treinada else ("-" if com_ia else ""),
                       f"{r.get('ia_vetos_validacao', 0)}/{r.get('ia_sinais_validacao', 0)}" if treinada else ("-" if com_ia else ""),
                       _fmt(r["pontuacao_treino"], 0), _fmt(r["pontuacao_validacao"], 0), r["mult_stop"], r["mult_alvo"],
                       mt.get("total_trades", 0), _fmt(mt.get("taxa_acerto", 0.0), 0), _fmt(mt.get("fator_lucro", 0.0)),
                       _fmt(mt.get("lucro_liquido", 0.0)), _fmt(mv.get("lucro_liquido", 0.0)), _fmt(mt.get("drawdown_maximo", 0.0))]
            tag = "topo" if r["posicao"] == 1 and r["pontuacao_final"] > 0 else ("inelegivel" if r["pontuacao_final"] <= 0 else "")
            self.arvore.insert("", "end", iid=r["nome"], values=valores, tags=(tag,))

    def _ranking_selecionado(self) -> Optional[dict]:
        sel = self.arvore.selection()
        if not sel:
            return self.ranking[0] if self.ranking else None
        return next((r for r in self.ranking if r["nome"] == sel[0]), None)

    def _usar_na_operacao(self):
        r = self._ranking_selecionado()
        if r is None:
            return
        self.var_estrategia_operacao.set(r["nome"])
        self._atualizar_descricao_estrategia()
        self.abas.select(self.aba_operacao)

    # ------------------------------------------------------------- detalhes
    def _abrir_detalhes(self):
        r = self._ranking_selecionado()
        if r is None:
            messagebox.showinfo("Detalhes", "Selecione uma estratégia do ranking.")
            return
        JanelaDetalhes(self, r)

    # ------------------------------------------------------------- aba operação
    def _construir_operacao(self):
        a = self.aba_operacao
        esquerda = ttk.Frame(a, width=380)
        esquerda.pack(side="left", fill="y", padx=(0, 10))
        esquerda.pack_propagate(False)
        direita = ttk.Frame(a)
        direita.pack(side="left", fill="both", expand=True)

        painel = ttk.LabelFrame(esquerda, text="Parâmetros da operação", padding=10)
        painel.pack(fill="x")
        ttk.Label(painel, text="Estratégia (do ranking)").grid(row=0, column=0, sticky="w")
        self.var_estrategia_operacao = tk.StringVar()
        self.combo_estrategia = ttk.Combobox(painel, textvariable=self.var_estrategia_operacao, state="readonly", width=34)
        self.combo_estrategia.grid(row=1, column=0, columnspan=2, sticky="we", pady=(0, 6))
        self.combo_estrategia.bind("<<ComboboxSelected>>", lambda _e: self._atualizar_descricao_estrategia())
        self.var_desc_estrategia = tk.StringVar(value="")
        ttk.Label(painel, textvariable=self.var_desc_estrategia, wraplength=340, foreground="#444").grid(
            row=2, column=0, columnspan=2, sticky="w", pady=(0, 8))

        ttk.Label(painel, text="Contratos").grid(row=3, column=0, sticky="w")
        self.var_contratos_op = tk.IntVar(value=self.cfg.contratos)
        ttk.Spinbox(painel, from_=1, to=1000, textvariable=self.var_contratos_op, width=8).grid(row=3, column=1, sticky="w")
        ttk.Label(painel, text="Modo").grid(row=4, column=0, sticky="w", pady=(6, 0))
        self.var_modo_op = tk.StringVar(value=self.cfg.execucao.modo)
        quadro_modo = ttk.Frame(painel)
        quadro_modo.grid(row=4, column=1, sticky="w", pady=(6, 0))
        ttk.Radiobutton(quadro_modo, text="Simulado", value="simulado", variable=self.var_modo_op).pack(side="left")
        ttk.Radiobutton(quadro_modo, text="REAL", value="real", variable=self.var_modo_op).pack(side="left", padx=6)
        self.var_ia_op = tk.BooleanVar(value=self.cfg.ia.ativar)
        ttk.Checkbutton(painel, text="Usar filtro de IA", variable=self.var_ia_op).grid(row=5, column=0, columnspan=2, sticky="w", pady=(6, 0))
        self.var_um_por_vez_op = tk.BooleanVar(value=self.cfg.execucao.um_trade_por_vez)
        ttk.Checkbutton(painel, text="Um trade por vez (aguarda zerar)",
                        variable=self.var_um_por_vez_op).grid(row=6, column=0, columnspan=2, sticky="w", pady=(0, 6))

        botoes = ttk.Frame(painel)
        botoes.grid(row=7, column=0, columnspan=2, sticky="we", pady=(6, 0))
        self.botao_iniciar = ttk.Button(botoes, text="▶ Iniciar operação", command=self._iniciar_operacao)
        self.botao_iniciar.pack(side="left", fill="x", expand=True)
        self.botao_parar = ttk.Button(botoes, text="■ Parar", command=self._parar_operacao, state="disabled", style="Perigo.TButton")
        self.botao_parar.pack(side="left", fill="x", expand=True, padx=(6, 0))

        status = ttk.LabelFrame(esquerda, text="Status", padding=10)
        status.pack(fill="x", pady=10)
        self.var_st_estado = tk.StringVar(value="Parado")
        self.var_st_conta = tk.StringVar(value="-")
        self.var_st_posicao = tk.StringVar(value="-")
        self.var_st_resultado = tk.StringVar(value="-")
        for i, (rot, var) in enumerate([("Estado", self.var_st_estado), ("Conta", self.var_st_conta),
                                        ("Posição", self.var_st_posicao), ("Resultado do dia", self.var_st_resultado)]):
            ttk.Label(status, text=rot + ":").grid(row=i, column=0, sticky="nw", pady=2)
            ttk.Label(status, textvariable=var, wraplength=260, style="Status.TLabel" if rot == "Estado" else "TLabel").grid(
                row=i, column=1, sticky="w", padx=6, pady=2)

        ttk.Label(esquerda, text="Fluxo sugerido: 1) configure  2) rode o backtest  3) opere em modo simulado por alguns dias\n"
                                 "4) só então use o modo real. Resultados passados não garantem resultados futuros.",
                  wraplength=360, foreground="#666").pack(fill="x", pady=4)

        ttk.Label(direita, text="Registro em tempo real").pack(anchor="w")
        self.texto_log = ScrolledText(direita, height=20, state="disabled", font=("Consolas", 9), wrap="word")
        self.texto_log.pack(fill="both", expand=True)
        self.texto_log.tag_configure("WARNING", foreground="#b8860b")
        self.texto_log.tag_configure("ERROR", foreground="#b00020")
        ttk.Button(direita, text="Limpar registro", command=self._limpar_log).pack(anchor="e", pady=4)

    def _atualizar_lista_estrategias_operacao(self):
        catalogo = {e.nome for e in construir_catalogo()}
        nomes = [r["nome"] for r in self.ranking if r["pontuacao_final"] > 0 and r["nome"] in catalogo]
        if self.ranking and not nomes and any(r["pontuacao_final"] > 0 for r in self.ranking):
            self.var_info_ranking.set(self.var_info_ranking.get() + "\nEste ranking foi gerado com estratégias que não existem "
                                      "mais no catálogo: rode o backtest novamente.")
        self.combo_estrategia["values"] = nomes
        if hasattr(self, "combo_estrategia_wf"):
            self._atualizar_lista_estrategias_walkforward()
        if nomes and self.var_estrategia_operacao.get() not in nomes:
            self.var_estrategia_operacao.set(nomes[0])
        elif not nomes:
            self.var_estrategia_operacao.set("")
        self._atualizar_descricao_estrategia()

    def _atualizar_descricao_estrategia(self):
        r = next((r for r in self.ranking if r["nome"] == self.var_estrategia_operacao.get()), None)
        if r is None:
            self.var_desc_estrategia.set("Nenhuma estratégia elegível. Rode o backtest na aba 2.")
        else:
            self.var_desc_estrategia.set(f"#{r['posicao']} • nota {r['pontuacao_final']} • stop {r['mult_stop']}xATR • "
                                         f"alvo {r['mult_alvo']}xATR\n{r['descricao']}")

    def _iniciar_operacao(self):
        if self.ocupado or self.thread_executor is not None:
            return
        if not self._aplicar_campos():
            return
        entrada = next((r for r in self.ranking if r["nome"] == self.var_estrategia_operacao.get()), None)
        if entrada is None:
            messagebox.showwarning("Operação", "Escolha uma estratégia do ranking (rode o backtest antes).")
            return
        self.cfg.contratos = int(self.var_contratos_op.get())
        self.cfg.execucao.modo = self.var_modo_op.get()
        self.cfg.ia.ativar = bool(self.var_ia_op.get())
        self.cfg.execucao.um_trade_por_vez = bool(self.var_um_por_vez_op.get())
        self.campos[(id(self.cfg.execucao), "um_trade_por_vez")][3].set(self.cfg.execucao.um_trade_por_vez)
        self.campos[(id(self.cfg), "contratos")][3].set(str(self.cfg.contratos))
        self.campos[(id(self.cfg.execucao), "modo")][3].set(self.cfg.execucao.modo)
        self.campos[(id(self.cfg.ia), "ativar")][3].set(self.cfg.ia.ativar)
        self.cfg.salvar()
        self.var_resumo.set(self.cfg.resumo())

        if self.cfg.execucao.modo == "real":
            if self.cfg.fonte_dados != "mt5":
                messagebox.showerror("Operação", "Modo REAL exige fonte de dados = mt5.")
                return
            if not messagebox.askyesno("CONFIRMAÇÃO — ORDENS REAIS",
                                       f"Ordens REAIS serão enviadas na conta logada no MT5.\n\n"
                                       f"Ativo: {self.cfg.ativo} {self.cfg.timeframe}\nEstratégia: {entrada['nome']}\n"
                                       f"Contratos: {self.cfg.contratos}\n\nDeseja continuar?", icon="warning", default="no"):
                return
        estrategia = servicos.instanciar_do_ranking(entrada)
        if estrategia is None:
            messagebox.showerror("Operação", f"A estratégia '{entrada['nome']}' não existe mais no catálogo. Rode o backtest novamente.")
            return
        self._ocupar(True, "Preparando operação...")
        self.botao_iniciar["state"] = "disabled"

        def tarefa():
            try:
                df = self.df
                if df is None and (self.cfg.ia.ativar or self.cfg.fonte_dados != "mt5"):
                    df = servicos.carregar_dados(self.cfg)
                    self.df = df
                self.executor = servicos.montar_executor(self.cfg, estrategia, df)
                self.fila.put(("exec_inicio",))
                self.executor.iniciar()
            except Exception as erro:
                self.fila.put(("erro", f"Falha na operação: {erro}"))
            finally:
                self.fila.put(("exec_fim",))
        self.thread_executor = threading.Thread(target=tarefa, daemon=True)
        self.thread_executor.start()

    def _parar_operacao(self):
        if self.executor is not None:
            self.executor.parar()
            self._definir_status("Encerrando operação...")

    def _atualizar_status_operacao(self):
        try:
            ex = self.executor
            if ex is not None and self.thread_executor is not None and self.thread_executor.is_alive() and ex.ativo:
                corretora = ex.corretora
                conta = corretora.obter_conta()
                self.var_st_conta.set(f"{conta.nome} | saldo {conta.saldo:,.2f} {conta.moeda}")
                pos = corretora.obter_posicao(self.cfg.ativo)
                if pos is None:
                    self.var_st_posicao.set("zerado")
                else:
                    self.var_st_posicao.set(f"{'COMPRADO' if pos.direcao == 1 else 'VENDIDO'} {pos.contratos} @ {pos.preco_entrada:.2f} "
                                            f"| stop {pos.stop:.2f} | alvo {pos.alvo:.2f}")
                self.var_st_resultado.set(f"{corretora.lucro_do_dia(self.cfg.ativo):+,.2f}")
        except Exception:
            pass
        self.raiz.after(3000, self._atualizar_status_operacao)

    # ------------------------------------------------------------- aba walk-forward
    def _construir_walkforward(self):
        a = self.aba_walkforward
        wf = self.cfg.walkforward
        controles = ttk.Frame(a)
        controles.pack(fill="x")
        ttk.Label(controles, text="Estratégia:").pack(side="left")
        self.var_estrategia_wf = tk.StringVar()
        self.combo_estrategia_wf = ttk.Combobox(controles, textvariable=self.var_estrategia_wf, state="readonly", width=40)
        self.combo_estrategia_wf.pack(side="left", padx=(4, 12))
        ttk.Label(controles, text="Janelas:").pack(side="left")
        self.var_janelas_wf = tk.IntVar(value=wf.n_janelas)
        ttk.Spinbox(controles, from_=2, to=30, textvariable=self.var_janelas_wf, width=5).pack(side="left", padx=(4, 12))
        ttk.Label(controles, text="Treino (fração):").pack(side="left")
        self.var_treino_wf = tk.StringVar(value=str(wf.proporcao_treino))
        ttk.Entry(controles, textvariable=self.var_treino_wf, width=6).pack(side="left", padx=(4, 12))
        self.var_ancorado_wf = tk.BooleanVar(value=wf.ancorado)
        ttk.Checkbutton(controles, text="Ancorado (treino cresce desde o início)", variable=self.var_ancorado_wf).pack(side="left", padx=(0, 12))
        self.botao_wf = ttk.Button(controles, text="▶ Rodar walk-forward", command=self._rodar_walkforward)
        self.botao_wf.pack(side="left")

        lote = ttk.Frame(a)
        lote.pack(fill="x", pady=(6, 0))
        self.botao_wf_lote = ttk.Button(lote, text="▶ Comparar as melhores do ranking", command=self._rodar_walkforward_lote)
        self.botao_wf_lote.pack(side="left")
        ttk.Label(lote, text="quantidade:").pack(side="left", padx=(8, 2))
        self.var_top_wf = tk.IntVar(value=wf.top_ranking)
        ttk.Spinbox(lote, from_=1, to=200, textvariable=self.var_top_wf, width=5).pack(side="left")
        ttk.Label(lote, text="  (usa o ranking carregado na aba 2; duplo clique numa linha da comparação abre o walk-forward dela)",
                  foreground="#666").pack(side="left")

        ttk.Label(a, text="O walk-forward divide o histórico em janelas consecutivas de TESTE. Em cada uma, stop/alvo são "
                          "reotimizados só no trecho anterior (treino) e aplicados no teste, que a otimização nunca viu. Se a "
                          "estratégia continua consistente janela após janela (e com eficiência próxima de 1), ela é robusta; se só "
                          "funciona no treino, está sobreajustada.", wraplength=1220, justify="left", foreground="#444").pack(fill="x", pady=6)
        self.var_resumo_wf = tk.StringVar(value="Nenhum walk-forward executado.")
        ttk.Label(a, textvariable=self.var_resumo_wf, wraplength=1220, justify="left").pack(fill="x")

        self.subabas_wf = ttk.Notebook(a)
        self.subabas_wf.pack(fill="both", expand=True, pady=(6, 4))
        quadro_janelas = ttk.Frame(self.subabas_wf)
        quadro_comparacao = ttk.Frame(self.subabas_wf)
        self.subabas_wf.add(quadro_janelas, text="  Janelas  ")
        self.subabas_wf.add(quadro_comparacao, text="  Comparação (melhores do ranking)  ")
        self.arvore_wf = self._criar_tabela(quadro_janelas, COLUNAS_JANELAS_WF, altura=7, esticar=("treino", "teste"))
        self.arvore_wf_lote = self._criar_tabela(quadro_comparacao, COLUNAS_COMPARACAO_WF, altura=7, esticar=("motivos",))
        self.arvore_wf_lote.bind("<Double-1>", lambda _e: self._walkforward_da_comparacao())
        for arv in (self.arvore_wf, self.arvore_wf_lote):
            arv.tag_configure("positivo", background="#e3f4e1")
            arv.tag_configure("negativo", background="#fbe4e4")
            arv.tag_configure("robusta", background="#e3f4e1")
            arv.tag_configure("moderada", background="#fff5d6")
            arv.tag_configure("fragil", background="#fbe4e4")
            arv.tag_configure("inconclusiva", foreground="#999")
            arv.tag_configure("erro", foreground="#b00020")

        ttk.Label(a, text="Curva de capital fora da amostra (janelas de teste concatenadas; faixas alternadas = janelas; "
                          "tracejado = stop/alvo fixos do ranking)").pack(anchor="w")
        self.tela_wf = tk.Canvas(a, height=200, bg="white", highlightthickness=1, highlightbackground="#ccc")
        self.tela_wf.pack(fill="both", expand=True)
        self.resultado_wf: Optional[dict] = None
        self.tela_wf.bind("<Configure>", lambda _e: self._desenhar_walkforward())
        self._atualizar_lista_estrategias_walkforward()

    def _criar_tabela(self, pai, colunas, altura=8, esticar=()):
        quadro = ttk.Frame(pai)
        quadro.pack(fill="both", expand=True)
        arvore = ttk.Treeview(quadro, columns=[c[0] for c in colunas], show="headings", height=altura, selectmode="browse")
        for chave, texto, largura in colunas:
            arvore.heading(chave, text=texto)
            arvore.column(chave, width=largura, minwidth=30, anchor="w" if chave in esticar or chave == "nome" else "center",
                          stretch=chave in esticar)
        rolagem = ttk.Scrollbar(quadro, orient="vertical", command=arvore.yview)
        arvore.configure(yscrollcommand=rolagem.set)
        arvore.pack(side="left", fill="both", expand=True)
        rolagem.pack(side="right", fill="y")
        return arvore

    def _atualizar_lista_estrategias_walkforward(self):
        catalogo = [e.nome for e in construir_catalogo()]
        do_ranking = [r["nome"] for r in self.ranking if r["nome"] in catalogo]
        nomes = do_ranking + [n for n in catalogo if n not in do_ranking]
        self.combo_estrategia_wf["values"] = nomes
        if nomes and self.var_estrategia_wf.get() not in nomes:
            self.var_estrategia_wf.set(nomes[0])

    def _parametros_walkforward(self) -> bool:
        try:
            wf = self.cfg.walkforward
            wf.n_janelas = int(self.var_janelas_wf.get())
            wf.proporcao_treino = float(str(self.var_treino_wf.get()).replace(",", "."))
            wf.ancorado = bool(self.var_ancorado_wf.get())
            wf.top_ranking = int(self.var_top_wf.get())
            return True
        except (ValueError, tk.TclError) as erro:
            messagebox.showerror("Walk-forward", f"Parâmetro inválido: {erro}")
            return False

    def _rodar_walkforward(self, nome: Optional[str] = None):
        if self.ocupado or not self._aplicar_campos() or not self._parametros_walkforward():
            return
        nome = nome or self.var_estrategia_wf.get()
        if not nome:
            messagebox.showwarning("Walk-forward", "Escolha uma estratégia.")
            return
        self.cfg.salvar()
        self._ocupar(True, f"Walk-forward de {nome}...")

        def tarefa():
            try:
                df = self._obter_dados()
                resultado = servicos.executar_walk_forward(self.cfg, df, nome, lambda k, t, s: self.fila.put(("progresso", k, t, s)))
                self.fila.put(("walkforward", resultado))
            except Exception as erro:
                self.fila.put(("erro", f"Falha no walk-forward: {erro}"))
            finally:
                self.fila.put(("livre",))
        threading.Thread(target=tarefa, daemon=True).start()

    def _rodar_walkforward_lote(self):
        if self.ocupado or not self._aplicar_campos() or not self._parametros_walkforward():
            return
        catalogo = {e.nome for e in construir_catalogo()}
        nomes = [r["nome"] for r in self.ranking if r["pontuacao_final"] > 0 and r["nome"] in catalogo][:self.cfg.walkforward.top_ranking]
        if not nomes:
            messagebox.showwarning("Walk-forward", "Nenhuma estratégia elegível no ranking. Rode o backtest na aba 2.")
            return
        self.cfg.salvar()
        self._ocupar(True, f"Walk-forward de {len(nomes)} estratégias do ranking...")

        def tarefa():
            try:
                df = self._obter_dados()
                lista = servicos.walk_forward_lote(self.cfg, df, nomes, lambda k, t, s: self.fila.put(("progresso", k, t, s)))
                self.fila.put(("walkforward_lote", lista))
            except Exception as erro:
                self.fila.put(("erro", f"Falha no walk-forward: {erro}"))
            finally:
                self.fila.put(("livre",))
        threading.Thread(target=tarefa, daemon=True).start()

    def _obter_dados(self):
        """Reaproveita os candles do último backtest quando o ativo/timeframe não mudou."""
        if self.df is None or len(self.df) < 500:
            self.df = servicos.carregar_dados(self.cfg)
            self.fila.put(("status", f"{len(self.df)} candles carregados."))
        return self.df

    def _walkforward_da_comparacao(self):
        sel = self.arvore_wf_lote.selection()
        if sel:
            self.var_estrategia_wf.set(sel[0])
            self._rodar_walkforward(sel[0])

    def _mostrar_walkforward(self, r: dict):
        self.resultado_wf = r
        self.var_resumo_wf.set(servicos.texto_walkforward(r))
        self.arvore_wf.delete(*self.arvore_wf.get_children())
        for j in r["janelas"]:
            t, tf = j["teste"], j.get("teste_fixo")
            valores = [j["numero"], f"{j['inicio_treino'][:16]} → {j['fim_treino'][:16]}", f"{j['inicio_teste'][:16]} → {j['fim_teste'][:16]}",
                       j["mult_stop"], j["mult_alvo"], _fmt(j["nota_treino"], 0), _fmt(j["nota_teste"], 0), t["trades"],
                       _fmt(t["lucro"]), _fmt(t["fator_lucro"]), _fmt(t["drawdown"]), _fmt(t["acerto"], 0),
                       "-" if j["eficiencia"] is None else _fmt(j["eficiencia"]), _fmt(tf["lucro"]) if tf else "-"]
            self.arvore_wf.insert("", "end", values=valores, tags=("positivo" if t["lucro"] > 0 else "negativo",))
        self.subabas_wf.select(0)
        self._desenhar_walkforward()

    def _mostrar_walkforward_lote(self, lista):
        self.arvore_wf_lote.delete(*self.arvore_wf_lote.get_children())
        for r in lista:
            m, mf = r.get("metricas_teste", {}), r.get("metricas_teste_fixo")
            valores = [r["posicao"], r["estrategia"], r["familia"], _fmt(r["pontuacao"], 1), r["veredito"],
                       f"{r['pct_janelas_positivas']:.0f}%", _fmt(r["eficiencia"]), f"{r['estabilidade_parametros'] * 100:.0f}%",
                       m.get("total_trades", 0), _fmt(m.get("lucro_liquido", 0.0)), _fmt(m.get("fator_lucro", 0.0)),
                       _fmt(m.get("drawdown_maximo", 0.0)), _fmt(mf["lucro_liquido"]) if mf else "-", "; ".join(r.get("motivos", []))]
            self.arvore_wf_lote.insert("", "end", iid=r["estrategia"], values=valores, tags=(r["veredito"],))
        self.subabas_wf.select(1)
        robustas = sum(1 for r in lista if r["veredito"] == "robusta")
        self.var_resumo_wf.set(f"Comparação concluída: {len(lista)} estratégias | {robustas} robusta(s) | "
                               f"melhor: {lista[0]['estrategia']} (pontuação WF {lista[0]['pontuacao']}, {lista[0]['veredito']})"
                               if lista else "Comparação sem resultados.")

    def _desenhar_walkforward(self):
        tela = self.tela_wf
        tela.delete("all")
        r = self.resultado_wf
        if r is None:
            tela.create_text(10, 10, anchor="nw", text="Rode um walk-forward para ver a curva fora da amostra.", fill="#666")
            return
        curva, cortes = r["curva_teste"], r["cortes_curva"]
        curva_fixo = r.get("curva_teste_fixo")
        largura, altura = max(tela.winfo_width(), 300), max(tela.winfo_height(), 120)
        margem = 44
        if len(curva) < 2:
            tela.create_text(10, 10, anchor="nw", text="Sem trades fora da amostra.", fill="#666")
            return
        todas = list(curva) + (list(curva_fixo) if curva_fixo else [])
        minimo, maximo = min(todas), max(todas)
        faixa = (maximo - minimo) or 1.0

        def ponto(i, v, total):
            x = margem + (largura - 2 * margem) * i / max(1, total - 1)
            y = altura - margem + 10 - (altura - 2 * margem) * (v - minimo) / faixa
            return x, y

        limites = cortes + [len(curva) - 1]
        for k in range(len(cortes)):
            x0 = ponto(limites[k], minimo, len(curva))[0]
            x1 = ponto(limites[k + 1], minimo, len(curva))[0]
            cor = "#f3f7fb" if k % 2 == 0 else "#ffffff"
            tela.create_rectangle(x0, 10, x1, altura - margem + 10, fill=cor, outline="")
            lucro = r["janelas"][k]["teste"]["lucro"]
            tela.create_text((x0 + x1) / 2, 12, anchor="n", text=f"J{k + 1}\n{lucro:+,.0f}", fill="#1a5" if lucro > 0 else "#b00020",
                             font=("Segoe UI", 8), justify="center")
        y0 = ponto(0, curva[0], len(curva))[1]
        tela.create_line(margem, y0, largura - margem, y0, fill="#bbb", dash=(3, 3))
        if curva_fixo and len(curva_fixo) > 1:
            pontos = [ponto(i, v, len(curva_fixo)) for i, v in enumerate(curva_fixo)]
            tela.create_line(*[c for p in pontos for c in p], fill="#888", width=1, dash=(4, 3))
        pontos = [ponto(i, v, len(curva)) for i, v in enumerate(curva)]
        tela.create_line(*[c for p in pontos for c in p], fill="#1f77b4", width=2)
        tela.create_text(margem, altura - margem + 14, anchor="nw", text=f"mín {minimo:,.0f}", fill="#333", font=("Segoe UI", 8))
        tela.create_text(4, 10, anchor="nw", text=f"máx\n{maximo:,.0f}", fill="#333", font=("Segoe UI", 8))
        tela.create_text(largura - margem, altura - margem + 14, anchor="ne",
                         text=f"{len(curva) - 1} trades | final {curva[-1]:,.0f} | veredito {r['veredito']}", fill="#333", font=("Segoe UI", 8))

    # ------------------------------------------------------------- aba estratégias
    def _construir_estrategias(self):
        a = self.aba_estrategias
        topo = ttk.Frame(a)
        topo.pack(fill="x")
        ttk.Label(topo, text="Família:").pack(side="left")
        self.var_familia = tk.StringVar(value="todas")
        ttk.Combobox(topo, textvariable=self.var_familia, values=["todas"] + sorted(familias()), state="readonly",
                     width=16).pack(side="left", padx=6)
        self.var_familia.trace_add("write", lambda *_: self._preencher_estrategias())
        self.var_total_estrategias = tk.StringVar()
        ttk.Label(topo, textvariable=self.var_total_estrategias).pack(side="left", padx=12)
        quadro = ttk.Frame(a)
        quadro.pack(fill="both", expand=True, pady=6)
        self.arvore_estrategias = ttk.Treeview(quadro, columns=("n", "nome", "familia", "stop", "alvo", "descricao"), show="headings")
        for chave, texto, largura in [("n", "#", 40), ("nome", "Nome", 220), ("familia", "Família", 110),
                                      ("stop", "Stop padrão", 80), ("alvo", "Alvo padrão", 80), ("descricao", "Descrição", 600)]:
            self.arvore_estrategias.heading(chave, text=texto)
            self.arvore_estrategias.column(chave, width=largura, anchor="w", stretch=chave == "descricao")
        rolagem = ttk.Scrollbar(quadro, orient="vertical", command=self.arvore_estrategias.yview)
        self.arvore_estrategias.configure(yscrollcommand=rolagem.set)
        self.arvore_estrategias.pack(side="left", fill="both", expand=True)
        rolagem.pack(side="right", fill="y")
        self._preencher_estrategias()

    def _preencher_estrategias(self):
        self.arvore_estrategias.delete(*self.arvore_estrategias.get_children())
        familia = self.var_familia.get()
        catalogo = construir_catalogo()
        n = 0
        for i, e in enumerate(catalogo, 1):
            if familia != "todas" and e.familia != familia:
                continue
            n += 1
            self.arvore_estrategias.insert("", "end", values=(i, e.nome, e.familia, e.stop_atr_padrao, e.alvo_atr_padrao, e.descricao))
        self.var_total_estrategias.set(f"{n} de {len(catalogo)} estratégias")

    # ------------------------------------------------------------- fila / utilidades
    def _processar_fila(self):
        try:
            while True:
                evento = self.fila.get_nowait()
                tipo = evento[0]
                if tipo == "log":
                    self._anexar_log(evento[1], evento[2])
                elif tipo == "status":
                    self._definir_status(evento[1])
                elif tipo == "progresso":
                    k, total, nome = evento[1], evento[2], evento[3]
                    self.progresso["maximum"] = total
                    self.progresso["value"] = k
                    self._definir_status(f"Avaliando {k}/{total}: {nome}")
                elif tipo == "ranking":
                    self.ranking, self.df = evento[1], evento[2]
                    self._preencher_ranking(self.ranking)
                    self._atualizar_lista_estrategias_operacao()
                    topo = self.ranking[0]
                    self.var_info_ranking.set(f"Ranking salvo em {evento[3]} | {len(self.df)} candles")
                    dados = servicos.carregar_ranking(self.cfg)
                    diag = (dados or {}).get("dados", {}).get("diagnostico")
                    if topo["pontuacao_final"] > 0:
                        self._definir_status(f"Concluído. Selecionada: {topo['nome']} (stop {topo['mult_stop']}xATR, alvo {topo['mult_alvo']}xATR)")
                        if diag:
                            self.var_info_ranking.set(self.var_info_ranking.get() + "\n" + servicos.texto_diagnostico(diag))
                    else:
                        self._definir_status("Concluído, mas nenhuma estratégia atingiu consistência mínima.")
                        texto = servicos.texto_diagnostico(diag) if diag else ""
                        self.var_info_ranking.set(self.var_info_ranking.get() + "\n" + texto)
                        self._anexar_log(texto, logging.WARNING)
                        messagebox.showwarning("Nenhuma estratégia elegível",
                                               texto or "Verifique quantidade de candles, horário e distância mínima de stop.")
                    self.abas.select(self.aba_backtest)
                elif tipo == "walkforward":
                    self._mostrar_walkforward(evento[1])
                    self._definir_status(f"Walk-forward concluído: {evento[1]['estrategia']} → {evento[1]['veredito']} "
                                         f"(pontuação {evento[1]['pontuacao']}). Salvo em {evento[1].get('arquivo', '')}")
                    self.abas.select(self.aba_walkforward)
                elif tipo == "walkforward_lote":
                    self._mostrar_walkforward_lote(evento[1])
                    self._definir_status("Comparação walk-forward concluída.")
                    self.abas.select(self.aba_walkforward)
                elif tipo == "conexao":
                    self.var_conexao.set(evento[1])
                    self._definir_status("Conexão com o MT5 OK.")
                elif tipo == "erro":
                    self._definir_status(evento[1])
                    self._anexar_log(evento[1], logging.ERROR)
                    messagebox.showerror("Erro", evento[1])
                elif tipo == "livre":
                    self._ocupar(False)
                elif tipo == "exec_inicio":
                    self._ocupar(False)
                    self.botao_parar["state"] = "normal"
                    self.var_st_estado.set(f"OPERANDO ({self.cfg.execucao.modo.upper()})")
                    self._definir_status(f"Operando {self.cfg.ativo} {self.cfg.timeframe} em modo {self.cfg.execucao.modo}.")
                    self.abas.select(self.aba_operacao)
                elif tipo == "exec_fim":
                    self._ocupar(False)
                    self.thread_executor = None
                    self.executor = None
                    self.botao_iniciar["state"] = "normal"
                    self.botao_parar["state"] = "disabled"
                    self.var_st_estado.set("Parado")
                    self.var_st_posicao.set("-")
                    self._definir_status("Operação encerrada.")
        except queue.Empty:
            pass
        self.raiz.after(150, self._processar_fila)

    def _anexar_log(self, texto: str, nivel: int):
        self.texto_log["state"] = "normal"
        tag = "ERROR" if nivel >= logging.ERROR else ("WARNING" if nivel >= logging.WARNING else "")
        self.texto_log.insert("end", texto + "\n", tag)
        if int(self.texto_log.index("end-1c").split(".")[0]) > 3000:
            self.texto_log.delete("1.0", "500.0")
        self.texto_log.see("end")
        self.texto_log["state"] = "disabled"

    def _limpar_log(self):
        self.texto_log["state"] = "normal"
        self.texto_log.delete("1.0", "end")
        self.texto_log["state"] = "disabled"

    def _definir_status(self, texto: str):
        self.var_status.set(texto)

    def _ocupar(self, ocupado: bool, texto: str = ""):
        self.ocupado = ocupado
        for botao in (self.botao_backtest, self.botao_wf, self.botao_wf_lote):
            botao["state"] = "disabled" if ocupado else "normal"
        if texto:
            self._definir_status(texto)
        if not ocupado:
            self.progresso["value"] = 0

    def _fechar(self):
        if self.thread_executor is not None and self.thread_executor.is_alive():
            if not messagebox.askyesno("Sair", "A operação automática está ativa. Deseja encerrá-la e sair?"):
                return
            self._parar_operacao()
        self.raiz.destroy()

    def executar(self):
        self.raiz.mainloop()


# ====================================================================== detalhes
class JanelaDetalhes(tk.Toplevel):
    def __init__(self, app: Aplicativo, entrada: dict):
        super().__init__(app.raiz)
        self.app = app
        self.entrada = entrada
        self.title(f"Detalhes — {entrada['nome']}")
        self.geometry("1000x680")
        r = entrada
        ttk.Label(self, text=f"{r['nome']}  ({r['familia']})", style="Titulo.TLabel").pack(anchor="w", padx=10, pady=(10, 2))
        ttk.Label(self, text=r["descricao"], wraplength=960).pack(anchor="w", padx=10)
        ttk.Label(self, text=f"Parâmetros: {r['parametros']}   |   stop {r['mult_stop']}xATR   alvo {r['mult_alvo']}xATR   |   "
                             f"nota final {r['pontuacao_final']} (treino {r['pontuacao_treino']} / validação {r['pontuacao_validacao']})",
                  wraplength=960).pack(anchor="w", padx=10, pady=(2, 6))
        ct, cv = r.get("consistencia_treino", {}), r.get("consistencia_validacao", {})
        ttk.Label(self, text=f"Consistência treino: {ct.get('janelas_positivas_pct', '-')}% janelas positivas, estabilidade "
                             f"{ct.get('estabilidade', '-')}, R² {ct.get('r2', '-')}   |   validação: {cv.get('janelas_positivas_pct', '-')}% "
                             f"janelas positivas, estabilidade {cv.get('estabilidade', '-')}, R² {cv.get('r2', '-')}",
                  wraplength=960, foreground="#444").pack(anchor="w", padx=10)

        if r.get("ia_treinada"):
            ttk.Label(self, text=f"Filtro de IA (treinado só no treino, aplicado na validação): nota com IA "
                                 f"{r['pontuacao_final_com_ia']} vs sem IA {r['pontuacao_final_sem_ia']} | vetou "
                                 f"{r['ia_vetos_validacao']} de {r['ia_sinais_validacao']} sinais da validação",
                      wraplength=960, foreground="#1a5").pack(anchor="w", padx=10)
        quadro = ttk.Frame(self)
        quadro.pack(fill="x", padx=10, pady=8)
        blocos = [("Treino", "metricas_treino"), ("Validação (fora da amostra)", "metricas_validacao"),
                  ("Período completo", "metricas_total")]
        if r.get("ia_treinada"):
            blocos.insert(2, ("Validação com IA", "metricas_validacao_com_ia"))
        for coluna, (titulo, chave) in enumerate(blocos):
            lf = ttk.LabelFrame(quadro, text=titulo, padding=4)
            lf.grid(row=0, column=coluna, sticky="nsew", padx=4)
            quadro.columnconfigure(coluna, weight=1)
            arv = ttk.Treeview(lf, columns=("m", "v"), show="headings", height=len(CHAVES_METRICAS))
            arv.heading("m", text="Métrica")
            arv.heading("v", text="Valor")
            arv.column("m", width=130, anchor="w")
            arv.column("v", width=90, anchor="e")
            m = r.get(chave, {})
            for k, rotulo in CHAVES_METRICAS:
                arv.insert("", "end", values=(rotulo, _fmt(m.get(k))))
            arv.pack(fill="both", expand=True)

        ttk.Label(self, text="Curva de capital (período completo, com stop/alvo ajustados)").pack(anchor="w", padx=10)
        self.tela = tk.Canvas(self, height=230, bg="white", highlightthickness=1, highlightbackground="#ccc")
        self.tela.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        self.tela.create_text(10, 10, anchor="nw", text="Calculando curva...", fill="#666")
        threading.Thread(target=self._calcular_curva, daemon=True).start()

    def _calcular_curva(self):
        try:
            df = self.app.df
            if df is None:
                df = servicos.carregar_dados(self.app.cfg)
                self.app.df = df
            estrategia = servicos.instanciar_do_ranking(self.entrada)
            resultado = servicos.backtest_detalhado(self.app.cfg, df, estrategia)
            curva = resultado.curva_capital(self.app.cfg.capital_inicial)
            corte_barras = int(len(df) * self.app.cfg.backtest.proporcao_treino)
            corte = sum(1 for t in resultado.trades if t.indice_entrada < corte_barras)
            self.after(0, lambda: self._desenhar(curva, corte))
        except Exception as erro:
            self.after(0, lambda: self.tela.create_text(10, 30, anchor="nw", text=f"Não foi possível calcular: {erro}", fill="#b00020"))

    def _desenhar(self, curva, corte):
        self.update_idletasks()
        tela = self.tela
        tela.delete("all")
        largura, altura = max(tela.winfo_width(), 300), max(tela.winfo_height(), 150)
        margem = 40
        if len(curva) < 2:
            tela.create_text(10, 10, anchor="nw", text="Sem trades.", fill="#666")
            return
        minimo, maximo = min(curva), max(curva)
        faixa = (maximo - minimo) or 1.0

        def ponto(i, v):
            x = margem + (largura - 2 * margem) * i / (len(curva) - 1)
            y = altura - margem + 10 - (altura - 2 * margem) * (v - minimo) / faixa
            return x, y

        x_corte = ponto(corte, minimo)[0]
        tela.create_rectangle(x_corte, 10, largura - margem, altura - margem + 10, fill="#f3f7fb", outline="")
        tela.create_text(x_corte + 4, 12, anchor="nw", text="validação", fill="#888", font=("Segoe UI", 8))
        pontos = [ponto(i, v) for i, v in enumerate(curva)]
        tela.create_line(*[c for p in pontos for c in p], fill="#1f77b4", width=2)
        y0 = ponto(0, curva[0])[1]
        tela.create_line(margem, y0, largura - margem, y0, fill="#bbb", dash=(3, 3))
        tela.create_text(margem, 12, anchor="nw", text=f"máx {maximo:,.0f}", fill="#333", font=("Segoe UI", 8))
        tela.create_text(margem, altura - margem + 14, anchor="nw", text=f"mín {minimo:,.0f}", fill="#333", font=("Segoe UI", 8))
        tela.create_text(largura - margem, altura - margem + 14, anchor="ne",
                         text=f"{len(curva) - 1} trades | final {curva[-1]:,.0f}", fill="#333", font=("Segoe UI", 8))


# ====================================================================== símbolos
class JanelaSimbolos(tk.Toplevel):
    """Lista os símbolos da corretora que contêm um texto; duplo clique copia o nome para o campo Ativo."""

    def __init__(self, app: Aplicativo):
        super().__init__(app.raiz)
        self.app = app
        self.title("Procurar símbolo na corretora")
        self.geometry("760x460")
        topo = ttk.Frame(self, padding=8)
        topo.pack(fill="x")
        ttk.Label(topo, text="Nome contém:").pack(side="left")
        self.var_filtro = tk.StringVar(value=("".join(c for c in app.cfg.ativo if c.isalpha())[:3] or "WIN"))
        entrada = ttk.Entry(topo, textvariable=self.var_filtro, width=16)
        entrada.pack(side="left", padx=6)
        entrada.bind("<Return>", lambda _e: self._buscar())
        ttk.Button(topo, text="Buscar", command=self._buscar).pack(side="left")
        self.var_msg = tk.StringVar(value="Duplo clique em um símbolo para usá-lo como ativo.")
        ttk.Label(self, textvariable=self.var_msg, foreground="#444", wraplength=740).pack(fill="x", padx=8)
        quadro = ttk.Frame(self, padding=8)
        quadro.pack(fill="both", expand=True)
        self.arvore = ttk.Treeview(quadro, columns=("nome", "descricao", "visivel", "caminho"), show="headings")
        for chave, texto, largura in [("nome", "Nome", 110), ("descricao", "Descrição", 260), ("visivel", "No Observador", 90),
                                      ("caminho", "Caminho", 240)]:
            self.arvore.heading(chave, text=texto)
            self.arvore.column(chave, width=largura, anchor="w")
        rolagem = ttk.Scrollbar(quadro, orient="vertical", command=self.arvore.yview)
        self.arvore.configure(yscrollcommand=rolagem.set)
        self.arvore.pack(side="left", fill="both", expand=True)
        rolagem.pack(side="right", fill="y")
        self.arvore.bind("<Double-1>", lambda _e: self._usar())
        ttk.Button(self, text="Usar símbolo selecionado", command=self._usar).pack(pady=(0, 8))
        self._buscar()

    def _buscar(self):
        filtro = self.var_filtro.get().strip()
        self.var_msg.set("Consultando a corretora...")

        def tarefa():
            try:
                simbolos = servicos.procurar_simbolos(self.app.cfg, filtro)
                self.after(0, lambda: self._preencher(simbolos, filtro))
            except Exception as erro:
                self.after(0, lambda: self.var_msg.set(f"Erro: {erro}"))
        threading.Thread(target=tarefa, daemon=True).start()

    def _preencher(self, simbolos, filtro):
        self.arvore.delete(*self.arvore.get_children())
        for s in simbolos:
            self.arvore.insert("", "end", values=(s["nome"], s["descricao"], "sim" if s["visivel"] else "não", s["caminho"]))
        if simbolos:
            self.var_msg.set(f"{len(simbolos)} símbolo(s) contendo '{filtro}'. Para o mini índice, prefira o contrato contínuo "
                             f"(WIN$N, WIN$, WINFUT...) se ele existir; senão use o contrato vigente (ex.: WINV26).")
        else:
            self.var_msg.set(f"Nenhum símbolo contendo '{filtro}'. Verifique se a conta está logada no MT5.")

    def _usar(self):
        sel = self.arvore.selection()
        if not sel:
            return
        nome = self.arvore.item(sel[0], "values")[0]
        self.app.campos[(id(self.app.cfg), "ativo")][3].set(nome)
        self.app.campos[(id(self.app.cfg), "fonte_dados")][3].set("mt5")
        self.app._aplicar_campos()
        self.app._definir_status(f"Ativo definido como {nome}. Clique em 'Salvar configuração'.")
        self.destroy()


def iniciar_interface(cfg: Configuracao) -> None:
    Aplicativo(cfg).executar()
