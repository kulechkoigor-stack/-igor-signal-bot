import pandas as pd
import ta

def add_indicators(df):
    df["rsi"] = ta.momentum.RSIIndicator(
        df["close"], window=14
    ).rsi()

    df["ema"] = ta.trend.EMAIndicator(
        df["close"], window=50
    ).ema_indicator()

    return df


def get_signal(df):
    last = df.iloc[-1]

    if last["rsi"] < 30:
        return "LONG"

    if last["rsi"] > 70:
        return "SHORT"

    return "WAIT"
