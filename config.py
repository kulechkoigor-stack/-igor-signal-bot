import os

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

SCAN_INTERVAL = 300  # 5 хвилин

TIMEFRAME = "15m"

RSI_PERIOD = 14
EMA_FAST = 50
EMA_SLOW = 200

TP1 = 0.02
TP2 = 0.04
TP3 = 0.06
SL = 0.01
