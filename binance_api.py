from binance.client import Client
import pandas as pd

client = Client()

def get_usdt_futures_symbols():
    """Повертає всі USDT Futures пари."""
    info = client.futures_exchange_info()

    symbols = []

    for s in info["symbols"]:
        if (
            s["quoteAsset"] == "USDT"
            and s["status"] == "TRADING"
        ):
            symbols.append(s["symbol"])

    return symbols


def get_klines(symbol, interval="15m", limit=250):
    """Отримує свічки Binance Futures."""

    data = client.futures_klines(
        symbol=symbol,
        interval=interval,
        limit=limit,
    )

    df = pd.DataFrame(data)

    df = df.iloc[:, :6]

    df.columns = [
        "time",
        "open",
        "high",
        "low",
        "close",
        "volume",
    ]

    df["open"] = df["open"].astype(float)
    df["high"] = df["high"].astype(float)
    df["low"] = df["low"].astype(float)
    df["close"] = df["close"].astype(float)
    df["volume"] = df["volume"].astype(float)

    return df
