import asyncio

from config import SCAN_INTERVAL, TIMEFRAME
from binance_api import get_usdt_futures_symbols, get_klines
from indicators import add_indicators, get_signal
from telegram_bot import send_signal

sent_signals = set()


async def scan_market():
    print("🚀 IGOR Signal Bot запущено...")

    while True:
        try:
            symbols = get_usdt_futures_symbols()

            print(f"Перевіряю {len(symbols)} пар...")

            for symbol in symbols:

                df = get_klines(symbol, TIMEFRAME)

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

            await asyncio.sleep(SCAN_INTERVAL)

        except Exception as e:
            print(e)
            await asyncio.sleep(30)


if __name__ == "__main__":
    asyncio.run(scan_market())
