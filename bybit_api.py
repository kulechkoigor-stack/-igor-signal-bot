from pybit.unified_trading import HTTP
import pandas as pd

session = HTTP(testnet=False)


def get_usdt_symbols():
    return [
        "BTCUSDT",
        "ETHUSDT",
        "BNBUSDT",
        "SOLUSDT",
        "XRPUSDT",
        "DOGEUSDT",
        "ADAUSDT",
        "TRXUSDT",
        "LINKUSDT",
        "AVAXUSDT",
        "SUIUSDT",
        "TONUSDT",
        "DOTUSDT",
        "LTCUSDT",
        "BCHUSDT",
        "AAVEUSDT",
        "NEARUSDT",
        "APTUSDT",
        "ARBUSDT",
        "OPUSDT"
    ]


def get_klines(symbol, interval="15", limit=200):
    response = session.get_kline(
        category="linear",
        symbol=symbol,
        interval=interval,
        limit=limit,
    )

    rows = response["result"]["list"]
    rows.reverse()

    df = pd.DataFrame(rows)

    df.columns = [
        "time",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "turnover",
    ]

    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = df[col].astype(float)

    return df
