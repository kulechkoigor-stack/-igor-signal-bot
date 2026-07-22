import asyncio

from bybit_api import get_usdt_symbols, get_klines
from indicators import add_indicators, get_signal
from telegram_bot import send_signal

CHECK_INTERVAL = 300
sent_signals = set()


async def scan():
    print("🚀 IGOR Signal Bot (Bybit) запущено")

    while True:
        try:
            symbols = get_usdt_symbols()

            print(f"Перевіряю {len(symbols)} пар")

            for symbol in symbols:
                try:
                    df = get_klines(symbol)

                    df = add_indicators(df)

                    signal = get_signal(df)

                    if signal:
                        key = f"{symbol}_{signal}"

                        if key not in sent_signals:
                            price = round(df.iloc[-1]["close"], 6)

                            await send_signal(
                                symbol,
                                signal,
                                price,
                            )

                            sent_signals.add(key)

                            print(f"{symbol} -> {signal}")

                except Exception as e:
                    print(f"{symbol}: {e}")

            await asyncio.sleep(CHECK_INTERVAL)

        except Exception as e:
            print(e)
            await asyncio.sleep(30)


if __name__ == "__main__":
    asyncio.run(scan())
