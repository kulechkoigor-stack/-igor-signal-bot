import logging
import pandas as pd
import numpy as np

from config import (
    ATR_SL_MULT,
    ATR_TP1_MULT,
    ATR_TP2_MULT,
    ATR_TP3_MULT,
    MIN_SCORE_NORMAL,
)

logger = logging.getLogger(__name__)

def generate_signals(symbol: str, df_15m, client=None, _stats=None) -> list[dict]:
    """
    Детектор Імпульсів (Pump & Dump v2.3):
    - Захищений від помилок розрахунку та порожніх даних.
    - Фільтрує слабкий об'єм, шпильки та ринковий шум.
    - Блокує шорти при надмірній перепроданості (RSI < 25), щоб уникнути відскоків проти стопів.
    """
    signals = []
    if _stats is None:
        _stats = {}
        
    _stats["raw"] = _stats.get("raw", 0) + 1

    if df_15m is None or len(df_15m) < 30:
        return signals

    try:
        # Безпечний розрахунок ATR
        if 'atr' not in df_15m.columns:
            high_low = df_15m['high'] - df_15m['low']
            high_close = np.abs(df_15m['high'] - df_15m['close'].shift())
            low_close = np.abs(df_15m['low'] - df_15m['close'].shift())
            ranges = pd.concat([high_low, high_close, low_close], axis=1)
            df_15m['atr'] = ranges.max(axis=1).rolling(14).mean()

        # Безпечний розрахунок Volume MA
        if 'vol_ma' not in df_15m.columns:
            df_15m['vol_ma'] = df_15m['volume'].rolling(window=20).mean()

        # Безпечний розрахунок RSI
        if 'rsi' not in df_15m.columns:
            delta = df_15m['close'].diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
            rs = gain / loss
            df_15m['rsi'] = 100 - (100 / (1 + rs))

        latest = df_15m.iloc[-1]
        
        open_val = float(latest.get('open', 0))
        high = float(latest.get('high', 0))
        low = float(latest.get('low', 0))
        close = float(latest.get('close', 0))
        volume = float(latest.get('volume', 0))
        vol_ma = float(latest.get('vol_ma', 1))
        atr = float(latest.get('atr', 0))
        rsi = float(latest.get('rsi', 50.0))

        if open_val <= 0 or close <= 0 or atr <= 0 or vol_ma <= 0:
            return signals

        # 1. Перевірка мінімального об'єму (мінімум у 2.3 рази вище за середнє)
        volume_ratio = volume / vol_ma
        if volume_ratio < 2.3:
            _stats["rejected_low_volume"] = _stats.get("rejected_low_volume", 0) + 1
            return signals

        # 2. Імпульс ціни
        price_change_pct = (close - open_val) / open_val * 100
        candle_range = high - low
        if candle_range <= 0:
            return signals

        direction = None
        score = 80.0

        # 3. Фільтр напрямку, довгих хвостів та захист по RSI
        if price_change_pct >= 1.8:  # LONG
            direction = "LONG"
            close_position_ratio = (high - close) / candle_range
            if close_position_ratio > 0.30:  # Верхній хвіст завеликий
                _stats["rejected_wick"] = _stats.get("rejected_wick", 0) + 1
                return signals
            if rsi > 85.0:  # Захист від надмірної перекупленості в лонг
                _stats["rejected_rsi"] = _stats.get("rejected_rsi", 0) + 1
                return signals

        elif price_change_pct <= -1.8:  # SHORT
            direction = "SHORT"
            close_position_ratio = (close - low) / candle_range
            if close_position_ratio > 0.30:  # Нижній хвіст завеликий
                _stats["rejected_wick"] = _stats.get("rejected_wick", 0) + 1
                return signals
            
            # ГОЛОВНИЙ ФІЛЬТР: Не шортимо, якщо монета вже повністю на дні (перепроданість)
            if rsi < 25.0:
                _stats["rejected_rsi_oversold"] = _stats.get("rejected_rsi_oversold", 0) + 1
                return signals
        else:
            _stats["rejected_low_momentum"] = _stats.get("rejected_low_momentum", 0) + 1
            return signals

        # Додаткові бали за потужний об'єм
        if volume_ratio >= 4.0:
            score += 15

        min_score_limit = MIN_SCORE_NORMAL if 'MIN_SCORE_NORMAL' in globals() else 75.0
        if score < min_score_limit:
            _stats["rejected_score"] = _stats.get("rejected_score", 0) + 1
            return signals

        # 4. Розрахунок стопів та тейків за ATR (множник 1.8 з конфігу)
        entry = close
        sl_distance = atr * ATR_SL_MULT
        tp1_distance = atr * ATR_TP1_MULT
        tp2_distance = atr * ATR_TP2_MULT
        tp3_distance = atr * ATR_TP3_MULT

        if direction == "LONG":
            sl = entry - sl_distance
            tp1 = entry + tp1_distance
            tp2 = entry + tp2_distance
            tp3 = entry + tp3_distance
        else:
            sl = entry + sl_distance
            tp1 = entry - tp1_distance
            tp2 = entry - tp2_distance
            tp3 = entry - tp3_distance

        if min(entry, sl, tp1, tp2, tp3) <= 0:
            return signals

        try:
            signal_entry_time = float(latest.name.timestamp())
        except (AttributeError, TypeError, ValueError, OverflowError):
            signal_entry_time = None

        signal = {
            "symbol": symbol,
            "direction": direction,
            "score": score,
            "entry": entry,
            "sl": sl,
            "tp1": tp1,
            "tp2": tp2,
            "tp3": tp3,
            "rr": 2.6,
            "signal_entry_time": signal_entry_time,
            "indicators": {
                "atr": atr,
                "volume_ratio": volume_ratio,
                "rsi": rsi
            },
            "pump_dump": {
                "confirmed": True
            }
        }
        
        signals.append(signal)
        return signals

    except Exception as exc:
        logger.error("[%s] Помилка в generate_signals: %s", symbol, exc, exc_info=True)
        return signals
