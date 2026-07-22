import ta

def add_indicators(df):
    """
    Додає технічні індикатори до DataFrame.
    """

    # EMA
    df["ema50"] = ta.trend.EMAIndicator(
        close=df["close"],
        window=50
    ).ema_indicator()

    df["ema200"] = ta.trend.EMAIndicator(
        close=df["close"],
        window=200
    ).ema_indicator()

    # RSI
    df["rsi"] = ta.momentum.RSIIndicator(
        close=df["close"],
        window=14
    ).rsi()

    # MACD
    macd = ta.trend.MACD(df["close"])

    df["macd"] = macd.macd()
    df["macd_signal"] = macd.macd_signal()
    df["macd_hist"] = macd.macd_diff()

    return df


def get_signal(df):
    """
    Повертає LONG, SHORT або None.
    """

    last = df.iloc[-1]

    # LONG
    if (
        last["ema50"] > last["ema200"]
        and last["rsi"] > 55
        and last["macd"] > last["macd_signal"]
    ):
        return "LONG"

    # SHORT
    if (
        last["ema50"] < last["ema200"]
        and last["rsi"] < 45
        and last["macd"] < last["macd_signal"]
    ):
        return "SHORT"

    return None
