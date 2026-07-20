from telegram import Bot
import os
import asyncio

TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

async def main():
    bot = Bot(token=TOKEN)
    await bot.send_message(
        chat_id=CHAT_ID,
        text="🚀 IGOR Signal Bot успішно запущений!"
    )

if __name__ == "__main__":
    asyncio.run(main())
