from telegram import Bot
from config import BOT_TOKEN, CHAT_ID

bot = Bot(token=BOT_TOKEN)


async def send_signal(symbol, signal, price):
    message = f"""
🚨 <b>IGOR SIGNAL BOT</b>

🪙 Монета: <b>{symbol}</b>

📈 Сигнал: <b>{signal}</b>

💵 Ціна: <b>{price}</b>

⚠️ Це автоматичний сигнал.
Перед входом перевір ринок самостійно.
"""

    await bot.send_message(
        chat_id=CHAT_ID,
        text=message,
        parse_mode="HTML",
    )
