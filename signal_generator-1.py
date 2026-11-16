import logging
import math

from config import (
    EMA_FAST,
    EMA_SLOW,
    ATR_SL_MULT,
    ATR_TP1_MULT,
    ATR_TP2_MULT,
    ATR_TP3_MULT,
    MIN_SCORE_NORMAL,
    MIN_SCORE_PUMP_DUMP,
)
from scorer import score_signal, detect_pump_dump

logger = logging.getLogger(__name__)


def _safe_float(value, default=0.0):
    try:
        result = float(value)
        return result if math.isfinite(result) else default
    except (TypeError, ValueError):
        return default


def _inc(stats, key):
    if stats is not None:
        stats[key] = stats.get(key, 0) + 1


def generate_signals(symbol, df, _stats=None):
    """
    Generate early LONG/SHORT signals from the latest candle.

    Compatibility:
    - Keeps the existing function signature and signal dictionary keys.
    - Keeps scorer.py, detect_pump_dump(), config.py, and ATR SL/TP settings.
    - Does not change Telegram or main.py.

    Important: df must contain 5-minute candles if the bot is intended
    to operate on the 5m timeframe. This function does not set timeframe.
    """
    signals = []

    if df is None or len(df) < 25:
        return signals

    try:
        required = ("close", "high", "low")
        if any(column not in df.columns for column in required):
            logger.warning("[%s] Missing OHLC columns in dataframe", symbol)
            return signals

        row = df.iloc[-1]
        prev = df.iloc[-2]

        close = _safe_float(row.get("close"))
        atr = _safe_float(row.get("atr"))
        ema_fast = _safe_float(row.get(f"ema{EMA_FAST}"))
        ema_slow = _safe_float(row.get(f"ema{EMA_SLOW}"))

        prev_close = _safe_float(prev.get("close"))
        prev_ema_fast = _safe_float(prev.get(f"ema{EMA_FAST}"))
        prev_ema_slow = _safe_float(prev.get(f"ema{EMA_SLOW}"))

        macd_hist = _safe_float(row.get("macd_hist"))
        prev_macd_hist = _safe_float(prev.get("macd_hist"))
        rsi = _safe_float(row.get("rsi"))

        volume = _safe_float(row.get("volume"))
        vol_ma = _safe_float(row.get("vol_ma"))

        if min(close, atr, ema_fast, ema_slow, prev_close) <= 0:
            return signals

        # Compare the current candle with the three candles before it.
        # The current candle is intentionally excluded from the range.
        previous_candles = df.iloc[-4:-1]
        prior_high = _safe_float(previous_candles["high"].max())
        prior_low = _safe_float(previous_candles["low"].min())

        long_breakout = prior_high > 0 and close > prior_high
        short_breakout = prior_low > 0 and close < prior_low

        long_ema_cross = prev_close <= prev_ema_fast and close > ema_fast
        short_ema_cross = prev_close >= prev_ema_fast and close < ema_fast

        # A rising/falling MACD histogram or stronger-than-average volume
        # confirms momentum. Volume alone is not a directional signal;
        # the price trigger above must also be present.
        volume_confirmed = vol_ma > 0 and volume >= vol_ma * 1.2
        long_momentum = macd_hist > prev_macd_hist or volume_confirmed
        short_momentum = macd_hist < prev_macd_hist or volume_confirmed

        # If RSI is missing/zero, don't reject solely because of missing data.
        long_rsi_ok = rsi == 0 or rsi <= 72
        short_rsi_ok = rsi == 0 or rsi >= 28

        early_long = (
            close > ema_fast
            and (long_breakout or long_ema_cross)
            and long_momentum
            and long_rsi_ok
        )
        early_short = (
            close < ema_fast
            and (short_breakout or short_ema_cross)
            and short_momentum
            and short_rsi_ok
        )

        pump_dump = detect_pump_dump(df) or {}
        pump_confirmed = bool(pump_dump.get("confirmed", False))
        is_late = bool(pump_dump.get("late", False))

        base_close = _safe_float(df.iloc[-4].get("close"))
        move_pct = (
            (close - base_close) / base_close * 100
            if base_close > 0
            else 0.0
        )

        for direction in ("LONG", "SHORT"):
            if direction == "LONG":
                trend = "Bullish"
                trend_ok = close > ema_fast > ema_slow
                early_entry = early_long
                aligned_move = bool(pump_dump.get("pump", False))
            else:
                trend = "Bearish"
                trend_ok = close < ema_fast < ema_slow
                early_entry = early_short
                aligned_move = bool(pump_dump.get("dump", False))

            # Accept either a fully aligned EMA trend or a specific early
            # breakout/cross trigger with momentum confirmation.
            if not trend_ok and not early_entry:
                _inc(_stats, "rejected_trend")
                continue

            if is_late and aligned_move:
                _inc(_stats, "rejected_late_entry")
                continue

            # Avoid entering against a very large move over the last 3 candles.
            if direction == "SHORT" and move_pct >= 3.0:
                _inc(_stats, "rejected_late_entry")
                continue
            if direction == "LONG" and move_pct <= -3.0:
                _inc(_stats, "rejected_late_entry")
                continue

            scored = score_signal(df, direction) or {}
            base_score = _safe_float(scored.get("score"))
            components = scored.get("components", {})
            signal_type = scored.get("signal_type") or "NORMAL"

            score = base_score
            bonus = _safe_float(pump_dump.get("bonus"))

            if (
                pump_confirmed
                and aligned_move
                and not is_late
                and base_score >= 85
            ):
                score = min(100.0, base_score + bonus)

            min_required = (
                MIN_SCORE_PUMP_DUMP
                if pump_confirmed and aligned_move
                else MIN_SCORE_NORMAL
            )

            # Small threshold adjustment only for a real early trigger.
            # Never fabricate extra score points.
            if early_entry and not trend_ok:
                min_required = max(0, min_required - 5)

            if _stats is not None:
                _stats["raw"] = _stats.get("raw", 0) + 1
                _stats.setdefault("candidates", []).append({
                    "symbol": symbol,
                    "direction": direction,
                    "score": score,
                    "signal_type": signal_type,
                    "pump_dump": pump_dump,
                    "early_entry": bool(early_entry and not trend_ok),
                })

            if score < min_required:
                _inc(_stats, "rejected_score")
                continue

            # Keep the existing ATR-based SL/TP behavior.
            sl_distance = atr * _safe_float(ATR_SL_MULT)
            tp1_distance = atr * _safe_float(ATR_TP1_MULT)
            tp2_distance = atr * _safe_float(ATR_TP2_MULT)
            tp3_distance = atr * _safe_float(ATR_TP3_MULT)

            if min(sl_distance, tp1_distance, tp2_distance, tp3_distance) <= 0:
                _inc(_stats, "rejected_invalid_atr")
                continue

            entry = close

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
                _inc(_stats, "rejected_invalid_prices")
                continue

            rr = abs(tp1 - entry) / abs(entry - sl)

            signals.append({
                "symbol": symbol,
                "direction": direction,
                "side": direction,
                "trend": trend,
                "signal_type": signal_type,
                "score": round(score, 2),
                "base_score": round(base_score, 2),
                "components": components,
                "entry": entry,
                "sl": sl,
                "tp1": tp1,
                "tp2": tp2,
                "tp3": tp3,
                "rr": round(rr, 2),
                "atr": atr,
                "atr_percent": atr / close * 100,
                "pump_dump": pump_dump,
                "early_entry": bool(early_entry and not trend_ok),
                "indicators": {
                    "close": close,
                    f"ema{EMA_FAST}": ema_fast,
                    f"ema{EMA_SLOW}": ema_slow,
                    "rsi": rsi,
                    "macd_hist": macd_hist,
                    "atr": atr,
                    "volume": volume,
                    "vol_ma": vol_ma,
                },
            })

    except Exception:
        logger.exception("[%s] Error generating signals", symbol)

    return signals
