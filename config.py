import os

# ─── Binance ────────────────────────────────────────────────────────────────
BINANCE_API_KEY    = os.environ.get("BINANCE_API_KEY", "")
BINANCE_API_SECRET = os.environ.get("BINANCE_API_SECRET", "")

# ─── Telegram ───────────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.environ.get("TELEGRAM_CHAT_ID", "2023946172")

# ─── Scanning & Filters ─────────────────────────────────────────────────────
SCAN_INTERVAL  = 300        # секунди між скануваннями (5 хв)
TIMEFRAME      = "15m"
TOP_N_PAIRS    = 150         # топ-150 ліквідних пар
MIN_SCORE           = 80    
MIN_SCORE_NORMAL    = 80    
MIN_SCORE_PUMP_DUMP = 80    # ВИПРАВЛЕНО: знижено з 90 до 80, щоб сканер пропускав імпульси з балом 85!
SIGNAL_COOLDOWN = 900       # 15 хв затримка перед повторним сигналом
MIN_ATR_PERCENT = 0.3       
MAX_ATR_PERCENT = 4.0       

# Глобальний фільтр ринку
BTC_TREND_FILTER = False

STABLECOIN_PAIRS = {
    "USDCUSDT",
    "USDTUSDT",
    "FDUSDUSDT",
    "TUSDUSDT",
    "USDPUSDT",
    "DAIUSDT",
}

# ─── Indicator Periods ──────────────────────────────────────────────────────
RSI_PERIOD      = 14        
EMA_FAST        = 7         
EMA_SLOW        = 99        
MACD_FAST       = 12
MACD_SLOW       = 26
MACD_SIGNAL_LEN = 9
ATR_PERIOD      = 14
VOLUME_MA_LEN   = 20

# ─── Risk Parameters (Оптимальні для швидких 15м імпульсів) ──────────────────
ATR_SL_MULT  = 1.8        # Повернуто оптимальний стоп для захисту від шуму
ATR_TP1_MULT = 1.6        # Швидкий перший тейк для фіксації частини
ATR_TP2_MULT = 2.6        # Стандартний здоровий R:R
ATR_TP3_MULT = 3.8        # Максимальна ціль для глибоких пампів

# ─── Score Weights ──────────────────────────────────────────────────────────
SCORE_EMA_TREND   = 25   
SCORE_EMA_CROSS   = 15   
SCORE_RSI         = 25   
SCORE_MACD        = 20   
SCORE_VOLUME      = 15   

COIN_SIGNAL_COOLDOWN = 14400  # 4 години ротації
