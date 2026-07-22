from pybit.unified_trading import HTTP
import pandas as pd

session = HTTP(testnet=False)

def get_usdt_symbols():
    response = session.get_instruments_info(
        category="linear"
    )

    symbols = []

    for item in response["result"]["list"]:
        if item["quoteCoin"] == "USDT":
            symbols.append(item["symbol"])

    return symbols


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

    for col in [
        "open",
        "high",
        "low",
        "close",
        "volume",
    ]:
        df[col] = df[col].astype(float)

    return df
