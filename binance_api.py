import requests
import pandas as pd

BASE_URL = "https://fapi.binance.com"


def get_usdt_futures_symbols():
    url = f"{BASE_URL}/fapi/v1/exchangeInfo"
    data = requests.get(url, timeout=10).json()

    symbols = []

    for s in data["symbols"]:
        if s["quoteAsset"] == "USDT" and s["status"] == "TRADING":
            symbols.append(s["symbol"])

    return symbols


def get_klines(symbol, interval="15m", limit=200):
    url = f"{BASE_URL}/fapi/v1/klines"

    params = {
        "symbol": symbol,
        "interval": interval,
        "limit": limit
    }

    data = requests.get(url, params=params, timeout=10).json()

    df = pd.DataFrame(data, columns=[
        "time", "open", "high", "low", "close",
        "volume", "_1", "_2", "_3", "_4", "_5", "_6"
    ])

    df = df[["time", "open", "high", "low", "close", "volume"]]

    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = df[col].astype(float)

    return df
