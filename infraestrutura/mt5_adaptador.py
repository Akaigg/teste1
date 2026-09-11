"""
Adaptador MetaTrader 5: provedor de dados + corretora real.

Usa a conta que já estiver logada no terminal MT5 aberto (mt5.initialize()
sem credenciais anexa ao terminal em execução). Requer Windows e o pacote
`MetaTrader5`.
"""
from __future__ import annotations

import threading
from datetime import datetime, timedelta
from functools import wraps
from typing import Optional

import pandas as pd

from dominio.modelos import InformacoesConta, Posicao

try:
    import MetaTrader5 as mt5
    MT5_DISPONIVEL = True
except ImportError:  # Linux/macOS ou pacote ausente
    mt5 = None
    MT5_DISPONIVEL = False


class ErroMT5(RuntimeError):
    pass


_TRAVA = threading.RLock()


def _sincronizado(metodo):
    """O pacote MetaTrader5 não é seguro para chamadas simultâneas de threads diferentes
    (executor + painel de status da interface); serializa todas as chamadas."""
    @wraps(metodo)
    def envolto(*args, **kwargs):
        with _TRAVA:
            return metodo(*args, **kwargs)
    return envolto


class AdaptadorMT5:
    def __init__(self, magic: int, desvio: int = 10, caminho_terminal: str = "", registrador=None):
        self.magic = magic
        self.desvio = desvio
        self.caminho_terminal = caminho_terminal
        self.registrador = registrador
        self._conectado = False

    # ------------------------------------------------------------ conexão
    @_sincronizado
    def conectar(self) -> InformacoesConta:
        if not MT5_DISPONIVEL:
            raise ErroMT5("Pacote MetaTrader5 não instalado (pip install MetaTrader5) ou sistema não suportado (somente Windows).")
        ok = mt5.initialize(self.caminho_terminal) if self.caminho_terminal else mt5.initialize()
        if not ok:
            raise ErroMT5(f"Falha ao conectar ao terminal MT5: {mt5.last_error()}. Abra o MT5 e faça login antes.")
        conta = mt5.account_info()
        if conta is None:
            raise ErroMT5("Terminal conectado, mas nenhuma conta logada.")
        self._conectado = True
        return InformacoesConta(login=conta.login, nome=conta.name, servidor=conta.server, saldo=conta.balance,
                                patrimonio=conta.equity, moeda=conta.currency, alavancagem=conta.leverage)

    @_sincronizado
    def desconectar(self) -> None:
        if MT5_DISPONIVEL and self._conectado:
            mt5.shutdown()
            self._conectado = False

    def _timeframe(self, tf: str):
        mapa = {"M1": mt5.TIMEFRAME_M1, "M2": mt5.TIMEFRAME_M2, "M3": mt5.TIMEFRAME_M3, "M5": mt5.TIMEFRAME_M5,
                "M10": mt5.TIMEFRAME_M10, "M15": mt5.TIMEFRAME_M15, "M30": mt5.TIMEFRAME_M30, "H1": mt5.TIMEFRAME_H1,
                "H4": mt5.TIMEFRAME_H4, "D1": mt5.TIMEFRAME_D1, "W1": mt5.TIMEFRAME_W1}
        if tf.upper() not in mapa:
            raise ErroMT5(f"Timeframe inválido: {tf}. Use um de {list(mapa)}")
        return mapa[tf.upper()]

    @_sincronizado
    def listar_simbolos(self, filtro: str = "") -> list:
        """Símbolos disponíveis na corretora cujo nome contém o filtro (ex.: 'WIN')."""
        padrao = f"*{filtro.strip()}*" if filtro.strip() else "*"
        simbolos = mt5.symbols_get(group=padrao) or []
        return sorted(
            [{"nome": s.name, "descricao": s.description, "visivel": bool(s.visible), "caminho": s.path} for s in simbolos],
            key=lambda x: x["nome"])

    def _garantir_simbolo(self, ativo: str):
        info = mt5.symbol_info(ativo)
        if info is None:
            base = "".join(c for c in ativo if c.isalpha())[:3]
            parecidos = [s["nome"] for s in self.listar_simbolos(base)][:15] if base else []
            dica = (f" Símbolos parecidos na sua corretora: {', '.join(parecidos)}." if parecidos
                    else " Nenhum símbolo parecido encontrado; verifique se a conta está logada e se o ativo está habilitado.")
            raise ErroMT5(f"Ativo '{ativo}' não existe com esse nome na sua corretora.{dica} "
                          f"Use o botão 'Procurar símbolo' (ou: python main.py simbolos {base}) e copie o nome exato.")
        if not info.visible:
            mt5.symbol_select(ativo, True)
            info = mt5.symbol_info(ativo)
        return info

    # --------------------------------------------------------- dados
    @_sincronizado
    def obter_candles(self, ativo: str, timeframe: str, quantidade: int) -> pd.DataFrame:
        self._garantir_simbolo(ativo)
        taxas = mt5.copy_rates_from_pos(ativo, self._timeframe(timeframe), 0, quantidade)
        if taxas is None or len(taxas) == 0:
            raise ErroMT5(f"Sem dados para {ativo} {timeframe}: {mt5.last_error()}")
        return self.converter_taxas(taxas)

    @staticmethod
    def converter_taxas(taxas) -> pd.DataFrame:
        """Converte o array de rates do MT5 no DataFrame padrão do robô (usa .values para NÃO alinhar índices)."""
        bruto = pd.DataFrame(taxas)
        tem_real = "real_volume" in bruto.columns and float(bruto["real_volume"].sum()) > 0
        volume = bruto["real_volume"] if tem_real else bruto["tick_volume"]
        df = pd.DataFrame({
            "abertura": bruto["open"].values.astype(float),
            "maxima": bruto["high"].values.astype(float),
            "minima": bruto["low"].values.astype(float),
            "fechamento": bruto["close"].values.astype(float),
            "volume": volume.values.astype(float),
        }, index=pd.DatetimeIndex(pd.to_datetime(bruto["time"].values, unit="s"), name="tempo"))
        df = df[~df.index.duplicated(keep="last")].sort_index()
        if df[["abertura", "maxima", "minima", "fechamento"]].isna().any().any():
            raise ErroMT5("Candles recebidos do MT5 contêm valores vazios (NaN).")
        return df

    # --------------------------------------------------------- conta / posições
    @_sincronizado
    def obter_conta(self) -> InformacoesConta:
        c = mt5.account_info()
        return InformacoesConta(login=c.login, nome=c.name, servidor=c.server, saldo=c.balance,
                                patrimonio=c.equity, moeda=c.currency, alavancagem=c.leverage)

    @_sincronizado
    def obter_posicao(self, ativo: str) -> Optional[Posicao]:
        posicoes = mt5.positions_get(symbol=ativo) or []
        for p in posicoes:
            if p.magic == self.magic:
                return Posicao(ativo=ativo, direcao=1 if p.type == mt5.POSITION_TYPE_BUY else -1, contratos=p.volume,
                               preco_entrada=p.price_open, stop=p.sl, alvo=p.tp, ticket=p.ticket,
                               data_abertura=pd.to_datetime(p.time, unit="s"))
        return None

    @_sincronizado
    def preco_referencia(self, ativo: str, direcao: int) -> float:
        tick = mt5.symbol_info_tick(ativo)
        return float(tick.ask if direcao == 1 else tick.bid)

    @_sincronizado
    def distancia_minima_stop(self, ativo: str) -> float:
        """Distância mínima (em pontos de preço) exigida pela plataforma entre o preço e o stop/alvo."""
        info = self._garantir_simbolo(ativo)
        nivel = max(int(info.trade_stops_level or 0), int(info.trade_freeze_level or 0))
        return float(nivel * (info.point or 1.0))

    @_sincronizado
    def ha_posicao_ou_ordem(self, ativo: str) -> bool:
        """Qualquer posição ou ordem pendente no ativo, de qualquer origem (manual, outro robô)."""
        return bool(mt5.positions_get(symbol=ativo)) or bool(mt5.orders_get(symbol=ativo))

    def _arredondar(self, preco: float, info) -> float:
        passo = info.trade_tick_size or info.point or 1.0
        return round(round(preco / passo) * passo, info.digits)

    def _modos_preenchimento(self, info):
        modos = []
        if info.filling_mode & 1:
            modos.append(mt5.ORDER_FILLING_FOK)
        if info.filling_mode & 2:
            modos.append(mt5.ORDER_FILLING_IOC)
        modos.append(mt5.ORDER_FILLING_RETURN)
        return modos

    @_sincronizado
    def enviar_ordem(self, ativo, direcao, contratos, stop, alvo, comentario="") -> bool:
        info = self._garantir_simbolo(ativo)
        tick = mt5.symbol_info_tick(ativo)
        preco = tick.ask if direcao == 1 else tick.bid
        tipo = mt5.ORDER_TYPE_BUY if direcao == 1 else mt5.ORDER_TYPE_SELL
        minimo = self.distancia_minima_stop(ativo) + max(0.0, float(tick.ask - tick.bid))  # MT5 compara SL/TP com o bid
        lado_certo = (stop < preco < alvo) if direcao == 1 else (alvo < preco < stop)
        if not lado_certo or abs(preco - stop) < minimo or abs(alvo - preco) < minimo:
            if self.registrador:
                self.registrador.warning(f"[MT5] Ordem NÃO enviada: stop {stop:.2f} / alvo {alvo:.2f} inválidos para preço "
                                         f"{preco:.2f} (distância mínima da plataforma: {minimo:.0f} pontos).")
            return False
        for modo in self._modos_preenchimento(info):
            pedido = {"action": mt5.TRADE_ACTION_DEAL, "symbol": ativo, "volume": float(contratos), "type": tipo,
                      "price": preco, "sl": self._arredondar(stop, info), "tp": self._arredondar(alvo, info),
                      "deviation": self.desvio, "magic": self.magic, "comment": comentario[:31],
                      "type_time": mt5.ORDER_TIME_DAY, "type_filling": modo}
            resultado = mt5.order_send(pedido)
            if resultado is not None and resultado.retcode == mt5.TRADE_RETCODE_DONE:
                if self.registrador:
                    self.registrador.info(f"[MT5] Ordem executada: {'COMPRA' if direcao == 1 else 'VENDA'} {contratos} {ativo} "
                                          f"@ {resultado.price} stop={pedido['sl']} alvo={pedido['tp']} ticket={resultado.order}")
                return True
            if resultado is not None and resultado.retcode != mt5.TRADE_RETCODE_INVALID_FILL:
                if self.registrador:
                    self.registrador.error(f"[MT5] Ordem rejeitada: retcode={resultado.retcode} {resultado.comment}")
                return False
        if self.registrador:
            self.registrador.error(f"[MT5] Nenhum modo de preenchimento aceito: {mt5.last_error()}")
        return False

    @_sincronizado
    def fechar_posicao(self, ativo: str, motivo: str = "") -> bool:
        p = self.obter_posicao(ativo)
        if p is None:
            return False
        info = self._garantir_simbolo(ativo)
        tick = mt5.symbol_info_tick(ativo)
        tipo = mt5.ORDER_TYPE_SELL if p.direcao == 1 else mt5.ORDER_TYPE_BUY
        preco = tick.bid if p.direcao == 1 else tick.ask
        for modo in self._modos_preenchimento(info):
            pedido = {"action": mt5.TRADE_ACTION_DEAL, "symbol": ativo, "volume": float(p.contratos), "type": tipo,
                      "position": p.ticket, "price": preco, "deviation": self.desvio, "magic": self.magic,
                      "comment": f"fechar:{motivo}"[:31], "type_time": mt5.ORDER_TIME_DAY, "type_filling": modo}
            resultado = mt5.order_send(pedido)
            if resultado is not None and resultado.retcode == mt5.TRADE_RETCODE_DONE:
                if self.registrador:
                    self.registrador.info(f"[MT5] Posição {p.ticket} fechada ({motivo}) @ {resultado.price}")
                return True
            if resultado is not None and resultado.retcode != mt5.TRADE_RETCODE_INVALID_FILL:
                break
        if self.registrador:
            self.registrador.error(f"[MT5] Falha ao fechar posição: {mt5.last_error()}")
        return False

    @_sincronizado
    def lucro_do_dia(self, ativo: str, dia=None) -> float:
        """Resultado dos negócios do robô no dia (data do candle, no horário do servidor)."""
        data = (pd.Timestamp(dia) if dia is not None else pd.Timestamp(datetime.now())).normalize()
        negocios = mt5.history_deals_get(datetime.now() - timedelta(days=3), datetime.now() + timedelta(days=1)) or []
        total = 0.0
        for d in negocios:
            if d.symbol == ativo and d.magic == self.magic and pd.to_datetime(d.time, unit="s").normalize() == data:
                total += d.profit + d.commission + d.swap + d.fee
        return float(total)
