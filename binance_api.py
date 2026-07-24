import requests
import pandas as pd

BASE_URL = "https://fapi.binance.com"


def get_usdt_futures_symbols():
    response = requests.get(f"{BASE_URL}/fapi/v1/exchangeInfo", timeout=10)
    print(response.status_code)
    print(response.text)

    data = response.json()

    if "symbols" not in data:
        raise Exception(data)

    return [
        s["symbol"]
        for s in data["symbols"]
        if s["quoteAsset"] == "USDT" and s["status"] == "TRADING"
    ]


def get_klines(symbol, interval="15m", limit=200):
    response = requests.get(
        f"{BASE_URL}/fapi/v1/klines",
        params={
            "symbol": symbol,
            "interval": interval,
            "limit": limit,
        },
        timeout=10,
    )

    data = response.json()

    df = pd.DataFrame(
        data,
        columns=[
            "time", "open", "high", "low", "close",
            "volume", "_1", "_2", "_3", "_4", "_5", "_6"
        ],
    )

    df = df[["time", "open", "high", "low", "close", "volume"]]

    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = df[col].astype(float)

    return df
