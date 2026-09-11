"""Leitura de candles a partir de CSV (exportação do MT5 ou qualquer OHLCV)."""
from __future__ import annotations

import pandas as pd

_ALIAS = {
    "time": "tempo", "date": "tempo", "datetime": "tempo", "data": "tempo", "tempo": "tempo",
    "open": "abertura", "abertura": "abertura",
    "high": "maxima", "maxima": "maxima", "máxima": "maxima",
    "low": "minima", "minima": "minima", "mínima": "minima",
    "close": "fechamento", "fechamento": "fechamento",
    "volume": "volume", "tick_volume": "volume", "vol": "volume", "real_volume": "volume_real",
}


class ProvedorCSV:
    def __init__(self, caminho: str):
        self.caminho = caminho

    def obter_candles(self, ativo: str, timeframe: str, quantidade: int) -> pd.DataFrame:
        df = pd.read_csv(self.caminho, sep=None, engine="python")
        df.columns = [_ALIAS.get(str(c).strip().lower().replace("<", "").replace(">", ""), str(c).strip().lower()) for c in df.columns]
        if "tempo" not in df.columns and {"date", "time"} & set(df.columns):
            df["tempo"] = df.get("date", "").astype(str) + " " + df.get("time", "").astype(str)
        faltando = {"tempo", "abertura", "maxima", "minima", "fechamento"} - set(df.columns)
        if faltando:
            raise ValueError(f"CSV sem as colunas obrigatórias: {sorted(faltando)}")
        if "volume" not in df.columns:
            df["volume"] = df.get("volume_real", 0)
        df["tempo"] = pd.to_datetime(df["tempo"])
        df = df.set_index("tempo").sort_index()
        df = df[["abertura", "maxima", "minima", "fechamento", "volume"]].astype(float)
        return df.tail(quantidade)
