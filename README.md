# Robô MT5 — seleção automática de estratégias

Robô de trading em Python, com **interface gráfica** (Tkinter, sem dependências extras) e também
menu/CLI de terminal, que:

- conecta-se à **conta já logada** no MetaTrader 5 (não pede usuário/senha);
- avalia **58 estratégias robustas** (8 famílias: pontuação ponderada de vários indicadores, regime adaptativo,
  estatística, confluência multi-timeframe, divergência por pivôs, fluxo de volume, estrutura de mercado e ensemble)
  em backtest sobre o histórico do ativo escolhido;
- ajusta automaticamente **stop e alvo** de cada estratégia (múltiplos de ATR) numa grade de valores;
- escolhe a estratégia com a **melhor consistência** (não o maior lucro), usando treino + validação fora da amostra;
- faz **walk-forward** (reotimização periódica + teste sempre fora da amostra) para verificar se a consistência se mantém;
- opera automaticamente com a quantidade de contratos configurada, em modo **simulado** (padrão) ou **real**;
- opcionalmente usa um **filtro de IA** (RandomForest) que veta sinais de baixa probabilidade.

> Resultados passados não garantem resultados futuros. O ranking é uma medida de regularidade histórica.
> Use primeiro o modo simulado e só depois o modo real, com o risco que você aceita perder.

## Instalação

```bash
pip install -r requirements.txt          # no Windows instala também o pacote MetaTrader5
python main.py                           # abre a INTERFACE GRÁFICA
python main.py menu                      # alternativa: menu interativo no terminal
```

## Interface gráfica

| Aba | O que faz |
|---|---|
| **1. Configuração** | todos os parâmetros do `configuracao.json` em formulário; botão *Testar conexão MT5* mostra a conta logada. Passe o mouse sobre um campo para ver a explicação na barra de status. |
| **2. Backtest & Ranking** | *Rodar backtest* avalia as 58 estratégias em segundo plano com barra de progresso; a tabela mostra o ranking (a 1ª colocada fica destacada). Duplo clique abre a janela de **detalhes** (métricas de treino / validação / total e curva de capital). *Usar na operação* leva a estratégia selecionada para a aba 3. |
| **3. Operação** | escolha da estratégia (entre as elegíveis do ranking), contratos, modo simulado/REAL, filtro de IA, botões *Iniciar* / *Parar*, painel de status (conta, posição, resultado do dia) e o registro em tempo real. O modo REAL pede confirmação explícita. |
| **4. Walk-forward** | escolha uma estratégia (do ranking ou do catálogo), o número de janelas, a fração de treino e se o treino é ancorado; *Rodar walk-forward* mostra o resumo (veredito, pontuação, eficiência, % de janelas lucrativas), a tabela janela a janela e a curva de capital fora da amostra. *Comparar as melhores do ranking* roda o walk-forward das N primeiras e ordena pela pontuação walk-forward. |
| **Estratégias** | catálogo completo filtrável por família. |

Sem MT5 (ex.: fonte `csv` ou `sintetico`) a operação simulada faz **replay** do histórico, útil para ver o robô funcionando.

Requisitos: Python 3.10+, MetaTrader 5 instalado e **aberto com a conta logada** (Windows). No Linux/macOS o
robô funciona com fonte `csv` ou `sintetico` (backtest e simulação por replay), mas não envia ordens.

## Uso rápido

```bash
python main.py configurar                      # assistente: ativo, timeframe, contratos, custos...
python main.py backtest                        # avalia todas as estratégias e gera o ranking
python main.py ranking --top 30                # mostra o ranking salvo
python main.py detalhes 1                      # métricas detalhadas da 1ª colocada (ou pelo nome)
python main.py operar                          # opera em modo SIMULADO com a melhor estratégia
python main.py operar --real                   # envia ordens REAIS (pede confirmação)
python main.py operar --estrategia donchian_20 # força uma estratégia do ranking
python main.py listar                          # lista as 58 estratégias
python main.py walkforward                     # walk-forward da melhor estratégia do ranking
python main.py walkforward --estrategia ensemble_0p3_4_3 --janelas 8 --treino 0.7
python main.py walkforward --top 10            # compara as 10 melhores do ranking fora da amostra
python main.py conexao                         # testa a conexão com o MT5

# sobrescritas rápidas (não alteram o arquivo de configuração):
python main.py --ativo WIN$N --timeframe M5 --contratos 1 backtest
python main.py --fonte csv --csv dados/meu_ativo_M5.csv backtest
python main.py --fonte sintetico --ativo TESTE backtest
```

## Configuração (`configuracao.json`)

| Campo | Significado |
|---|---|
| `ativo` | símbolo exatamente como aparece no MT5 |
| `timeframe` | M1, M5, M15, M30, H1, H4, D1 |
| `contratos` | quantidade por operação |
| `barras_historico` | candles usados no backtest |
| `fonte_dados` | `mt5`, `csv` ou `sintetico` |
| `valor_ponto` | valor financeiro de 1 ponto por contrato (para converter pontos em R$) |
| `custo_pontos_por_operacao` | custos (corretagem, emolumentos) convertidos em pontos por trade |
| `deslizamento_pontos` | slippage estimado por execução a mercado |
| `backtest.fechar_fim_dia` | encerra posições no último candle do dia |
| `backtest.sair_sinal_contrario` | encerra a posição ao surgir sinal oposto |
| `backtest.grade_stop_atr` / `grade_alvo_atr` | grade de multiplicadores testados para stop/alvo |
| `backtest.proporcao_treino` | fração dos dados usada no ajuste (o restante valida fora da amostra) |
| `backtest.n_janelas` | janelas temporais para medir consistência |
| `backtest.min_trades` | mínimo de trades no treino para a estratégia ser elegível |
| `execucao.modo` | `simulado` ou `real` |
| `execucao.perda_maxima_diaria` | trava de perda diária em moeda (0 = desativada) |
| `execucao.horario_inicio/fim` | janela de operação; fora dela a posição é encerrada |
| `execucao.um_trade_por_vez` | ligado: só entra com o ativo totalmente zerado (inclusive posições manuais) e, após win/loss, espera o próximo candle; o backtest aplica a mesma regra. Desligado: o sinal do próprio candle de saída pode reverter a posição imediatamente |
| `execucao.distancia_minima_stop_pontos` | distância mínima entre preço e stop/alvo exigida pela plataforma; 0 = ler `trade_stops_level` do MT5. Sinais com stop/alvo menores são descartados no backtest e ao vivo (aparecem em "Sinais descartados" nos detalhes) |
| `execucao.reavaliar_a_cada_horas` | reexecuta o ranking durante a operação e troca de estratégia se necessário (0 = nunca) |
| `ia.ativar` | liga o filtro de IA (requer scikit-learn). Com ele ativo, o ranking mostra as notas **sem IA** e **com IA** (filtro treinado só no treino e aplicado na validação) e é ordenado pela nota com IA |
| `ia.margem_probabilidade` | a IA veta o sinal quando a probabilidade prevista de lucro fica abaixo do ponto de equilíbrio da estratégia (perda média ÷ (ganho médio + perda média)) mais esta margem |
| `walkforward.n_janelas` | janelas de teste consecutivas do walk-forward |
| `walkforward.proporcao_treino` | fração de cada janela usada como treino (0.7 = treino com 70%, teste com 30%) |
| `walkforward.ancorado` | ligado: o treino sempre começa no início dos dados (cresce); desligado: janela deslizante de tamanho fixo |
| `walkforward.top_ranking` | quantas estratégias do ranking comparar no modo "lote" |

## As estratégias

Cada estratégia combina **vários indicadores com pesos e filtros de regime** em vez de um único cruzamento:

| Família | O que faz |
|---|---|
| `pontuacao_ponderada` | 6 indicadores normalizados em [-1, 1] com pesos formam uma pontuação; entra quando ela cruza o limiar com ≥4 componentes concordando e ATR em regime normal (`score_tendencia`, `score_reversao`, `score_momentum_volume`) |
| `regime_adaptativo` | votação de Efficiency Ratio, ADX e Choppiness classifica o regime; em tendência opera pullback, em lateral opera reversão nas bandas (`regime_adaptativo`); compressão→expansão de volatilidade com direção por pontuação (`expansao_volatilidade`) |
| `estatistica` | z-score em 3 horizontes filtrado pela autocorrelação dos retornos (`zscore_multiplo`); canal de regressão linear com R² e desvio residual (`canal_regressao`); continuação só com persistência estatística (`momentum_persistente`) |
| `confluencia` | dois timeframes superiores (reamostrados só com barras concluídas) precisam concordar antes do gatilho (`confluencia_tf`); 5 osciladores normalizados + divergência (`confluencia_osciladores`) |
| `divergencia` | divergência regular entre pivôs confirmados do preço e do RSI/MACD/CCI (`divergencia_pivos`) |
| `fluxo_volume` | pontuação de 6 medidores de fluxo (CMF, MFI, OBV, Force Index, delta agressor, VWAP) (`fluxo_ponderado`); bandas de desvio da VWAP diária (`bandas_vwap`) |
| `estrutura_mercado` | HH/HL x LH/LL por pivôs e rompimento de estrutura com volume (`estrutura_mercado`); força composta do candle com contexto (`forca_candle`) |
| `ensemble` | média ponderada do viés contínuo de 6 estratégias-membro com concordância mínima (`ensemble`) |

## Walk-forward (aba 4 / `python main.py walkforward`)

O ranking usa uma única divisão treino/validação. O walk-forward vai além: divide o histórico em **N janelas de teste
consecutivas**; para cada uma, stop/alvo são reotimizados **só no trecho anterior** (treino deslizante ou ancorado) e
aplicados no teste, que a otimização nunca viu. Os testes são concatenados numa única curva fora da amostra. Medidas:

- **% de janelas lucrativas** e **eficiência walk-forward** (lucro por barra no teste ÷ no treino; ≈1 = o teste rende
  tanto quanto o treino, < 0.5 sugere sobreajuste);
- **estabilidade dos parâmetros** (fração das janelas que escolheram a mesma combinação de stop/alvo);
- **pontuação walk-forward** (0–100: 35% janelas lucrativas, 25% eficiência, 20% fator de lucro, 10% drawdown,
  10% estabilidade; metade se houver prejuízo fora da amostra) e **veredito**: *robusta*, *moderada*, *frágil* ou
  *inconclusiva* (poucos trades);
- comparação com os **stop/alvo fixos** escolhidos pelo ranking (curva tracejada), para ver se reotimizar ajuda.

Resultados são salvos em `resultados/walkforward_<ativo>_<timeframe>_<estrategia>.json`.

## Como a melhor estratégia é escolhida

Para cada estratégia: (1) divide os dados em treino/validação; (2) no treino testa a grade de stop/alvo e
fica com a combinação de maior **pontuação de consistência**; (3) aplica essa combinação na validação;
(4) nota final = média ponderada com peso maior na validação.

Pontuação de consistência (0–100): % de janelas lucrativas (30%), estabilidade média/desvio entre janelas
(25%), fator de lucro limitado a 3 (20%), drawdown relativo (15%), linearidade da curva de capital (10%).
Estratégias com prejuízo líquido têm a nota reduzida à metade; com poucos trades recebem zero.

O backtest é conservador: entrada na abertura do candle seguinte ao sinal, stop verificado antes do alvo
quando ambos são tocados no mesmo candle, custos e slippage descontados.

## Fidelidade backtest × operação ao vivo ("trades fantasmas")

O backtest e o executor seguem **as mesmas regras**, e o teste `testes/test_fidelidade.py` garante que o executor
em replay reproduz o backtest trade a trade (mesma entrada, mesmo preço, mesmo resultado):

- sinal no fechamento do candle N → ordem preenchida na abertura do candle N+1 (o simulador faz o mesmo);
- stop/alvo ancorados ao preço negociável no envio (ask/bid no MT5; abertura no simulador);
- janela de horário avaliada sobre o **próximo** candle; saída no último candle da janela/do dia;
- perda máxima diária bloqueia novas entradas nos dois lados, inclusive logo após uma saída por sinal contrário;
- `um_trade_por_vez`: com a opção ligada, após uma saída só há nova entrada a partir do candle seguinte e com o ativo zerado; desligada, o sinal do próprio candle de saída pode gerar nova entrada — nos dois casos backtest e executor seguem a mesma regra;
- distância mínima de stop/alvo do MT5 (`trade_stops_level`): sinais que a plataforma rejeitaria são descartados também no backtest, e o adaptador MT5 recusa localmente ordens inválidas antes de enviá-las;
- custos e deslizamento descontados nos dois lados; o **stop** (que vira ordem a mercado) sofre deslizamento, o alvo (ordem limitada) não;
- com `fechar_fim_dia` desligado, a posição pode atravessar o fim da janela/dia nos dois lados, mas nunca há entradas fora da janela;
- todas as chamadas ao MT5 são serializadas por um lock (o pacote MetaTrader5 não é seguro para threads simultâneas).

O que **nenhum** backtest elimina e você deve considerar:

- **spread e liquidez**: o histórico do MT5 traz preço de negócio; ao vivo você compra no ask e vende no bid.
  Calibre `deslizamento_pontos` com o spread típico do ativo;
- **stop com gap**: o backtest aplica o `deslizamento_pontos` no stop, mas um gap grande (notícia, abertura) pode executar muito além disso;
- **stop e alvo no mesmo candle**: o backtest assume o stop (pior caso); ao vivo pode ter sido o alvo;
- **ordens rejeitadas** (margem, mercado fechado, modo de preenchimento) só existem ao vivo — aparecem no log;
- **filtro de IA**: em operação o modelo é retreinado com todo o histórico (mais dados que no ranking), então os vetos ao vivo não são exatamente os da coluna "Com IA"; o teste de fidelidade garante que, com o mesmo modelo, executor e backtest vetam os mesmos sinais;
- **aquecimento de indicadores**: ao vivo o executor usa uma janela recente de candles (2x `barras_minimas()` da
  estratégia, no mínimo 1000); EMAs muito longas podem diferir por frações de ponto do valor calculado com todo o
  histórico. As estratégias multi-timeframe (`confluencia_tf`, `ensemble`) pedem janelas maiores (fator × 300 candles)
  para as EMAs do timeframe superior convergirem — garanta `Max bars in chart` suficiente no MT5.

## Arquitetura (arquitetura limpa)

```
main.py                     ponto de entrada
config/configuracao.py      dataclasses + JSON de configuração
dominio/                    regras puras, sem dependências externas
  indicadores.py            indicadores técnicos
  modelos.py                Trade, Posicao, ResultadoBacktest...
  estrategias/              base.py (utilitários de pontuação ponderada) + 8 módulos por família + catalogo.py
aplicacao/                  casos de uso
  backtester.py             motor de simulação
  metricas.py               métricas de desempenho
  seletor.py                pontuação de consistência e ranking
  walkforward.py            análise walk-forward (reotimização por janelas + teste fora da amostra)
  executor.py               laço de operação ao vivo
  servicos.py               orquestração usada pela interface
  portas.py                 interfaces (ProvedorDados, Corretora)
infraestrutura/             adaptadores: MT5, CSV, sintético, simulador, replay, persistência, log
ia/filtro_ml.py             filtro de IA opcional
interface/                  janela.py (GUI Tkinter), menu.py (terminal), comandos.py (CLI), apresentacao.py
testes/                     pytest
```

### Adicionar uma estratégia

Crie uma classe herdando `EstrategiaBase` em um módulo de `dominio/estrategias/`, implemente
`gerar_sinais(df)` retornando uma Series com 1/-1/0 e adicione instâncias em `registrar()`.
Ela entra automaticamente no catálogo, no backtest, no ranking e no walk-forward. Se implementar
`vies(df)` (série contínua em [-1, 1]), ela também pode ser usada como membro do ensemble.

```python
class MinhaEstrategia(EstrategiaBase):
    identificador = "minha"
    familia = "pontuacao_ponderada"
    descricao = "..."
    stop_atr_padrao, alvo_atr_padrao = 2.0, 3.0

    def _componentes(self, df):
        f, a = df["fechamento"], ind.atr(df, 14)
        return {"rsi": (limitar((ind.rsi(f, 14) - 50) / 25), 1.0),
                "ema": (normalizar((ind.ema(f, 9) - ind.ema(f, 21)) / a, 1.0), 1.5)}

    def gerar_sinais(self, df):
        comp = self._componentes(df)
        score = pontuacao_ponderada(comp)                       # média ponderada em [-1, 1]
        return gatilho_por_limiar(score, self.p("limiar"))     # cruzamento de ±limiar
```

## Arquivos gerados

- `resultados/ranking_<ativo>_<timeframe>.json` — ranking completo com métricas.
- `resultados/walkforward_<ativo>_<timeframe>_<estrategia>.json` — janelas, métricas fora da amostra e veredito do walk-forward.
- `registros/robo_<data>.log` — log de tudo que o robô faz (ordens, sinais, erros).
