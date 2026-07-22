
import asyncio
from telegram_bot import send_signal

print("🚀 IGOR Signal Bot запущено")

async def main():
    while True:
        # Тут пізніше буде аналіз TradingView
        await send_signal(
            "BTCUSDT",
            "LONG",
            0
        )

        await asyncio.sleep(300)

if __name__ == "__main__":
    asyncio.run(main())
