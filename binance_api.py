import requests
import pandas as pd

BASE_URL = "https://fapi.binance.com"


def get_usdt_futures_symbols():
    response = requests.get(f"{BASE_URL}/fapi/v1/exchangeInfo", timeout=10)

    print("STATUS =", response.status_code)
    print("TEXT =", response.text)

    data = response.json()

    return [
        s["symbol"]
        for s in data["symbols"]
        if s["quoteAsset"] == "USDT" and s["status"] == "TRADING"
    ]
