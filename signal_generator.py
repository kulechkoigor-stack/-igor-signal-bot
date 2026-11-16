import math
import pandas as pd
import logging

from config import (
    EMA_FAST, EMA_SLOW,
    ATR_SL_MULT, ATR_TP1_MULT, ATR_TP2_MULT, ATR_TP3_MULT,
    MIN_SCORE_NORMAL, MIN_SCORE_PUMP_DUMP,
    SCORE_EMA_TREND, SCORE_EMA_CROSS,
    SCORE_RSI, SCORE_MACD, SCORE_VOLUME,
)

from scorer import score_signal, detect_pump_dump

logger = logging.getLogger(__name__)


def _fmt(value: float, decimals: int = 6) -> float:
    return round(value, decimals)


def _trend_direction(
    latest: "pd.Series",
    ema_fast_col: str,
    ema_slow_col: str
) -> str:
    close = latest["close"]
    ema_fast = latest.get(ema_fast_col)
    ema_slow = latest.get(ema_slow_col)

    if ema_fast is None or ema_slow is None:
        return "Neutral"

    if close > ema_fast and ema_fast > ema_slow:
        return "Bullish"

    if close < ema_fast and ema_fast < ema_slow:
        return "Bearish"

    return "Neutral"


def _recommended_leverage(atr: float, close: float) -> int:
    if close <= 0:
        return 5

    atr_pct = (atr / close) * 100

    if atr_pct < 1.5:
        return 15
    elif atr_pct < 3.0:
        return 10
    elif atr_pct < 5.0:
        return 5
    else:
        return 3


def generate_signals(
    symbol: str,
    df: pd.DataFrame,
    _stats: dict | None = None,
) -> list[dict]:
    """
    Generate NORMAL and MOMENTUM signals with trend filter protection.
    """

    if df is None or len(df) < 25:
        return []

    latest = df.iloc[-1]

    # PRICE
    try:
        close = float(latest["close"])
    except (TypeError, ValueError):
        close = 0.0

    if not math.isfinite(close) or close <= 0:
        logger.warning("[%s] Invalid close price (%s)", symbol, close)
        return []

    # ATR
    try:
        atr = float(latest.get("atr"))
    except (TypeError, ValueError):
        atr = 0.0

    if not math.isfinite(atr) or atr <= 0:
        logger.warning("[%s] Invalid ATR (%s)", symbol, atr)
        return []

    # PRICE PRECISION
    decimals = 2 if close >= 100 else (4 if close >= 1 else 6)

    # EMA FOR TREND VALIDATION
    ema_fast = float(latest.get(f"ema{EMA_FAST}", 0) or 0)
    ema_slow = float(latest.get(f"ema{EMA_SLOW}", 0) or 0)

    # PUMP / DUMP
    pd_result = detect_pump_dump(df)
    signals = []

    # LONG / SHORT
    for direction in ("LONG", "SHORT"):

        # Trend filter
        if ema_fast > 0 and ema_slow > 0:
            if direction == "LONG" and close < ema_fast:
                continue
            if direction == "SHORT" and close > ema_fast:
                continue

        result = score_signal(df, direction)
        base_score = result.get("score", 0)
        signal_type = result.get("signal_type")
        components = result.get("components", {})

        # PUMP/DUMP BONUS
        score = base_score
        pump_bonus_applied = 0

        if base_score >= 85 and pd_result.get("bonus", 0):
            if direction == "LONG" and pd_result.get("pump"):
                pump_bonus_applied = pd_result["bonus"]
            elif direction == "SHORT" and pd_result.get("dump"):
                pump_bonus_applied = pd_result["dump"]

            score = min(100, base_score + pump_bonus_applied)

        # Use the same score threshold policy as scanner.py
        min_required = (
            MIN_SCORE_PUMP_DUMP
            if pd_result.get("confirmed")
            else MIN_SCORE_NORMAL
        )

        # STATS
        if _stats is not None:
            _stats["raw"] = _stats.get("raw", 0) + 1
            _stats.setdefault("candidates", []).append({
                "symbol": symbol,
                "direction": direction,
                "score": score,
                "min_required": min_required,
            })

        # MINIMUM SCORE
        if score < min_required:
            if _stats is not None:
                _stats["rejected_score"] = (
                    _stats.get("rejected_score", 0) + 1
                )
            continue

        # ENTRY / SL / TP
        tick = 10 ** (-decimals)
        entry = close

        if direction == "LONG":
            sl = entry - ATR_SL_MULT * atr
            tp1 = entry + ATR_TP1_MULT * atr
            tp2 = entry + ATR_TP2_MULT * atr
            tp3 = entry + ATR_TP3_MULT * atr

            if tp2 <= tp1:
                tp2 = tp1 + tick
            if tp3 <= tp2:
                tp3 = tp2 + tick
        else:
            sl = entry + ATR_SL_MULT * atr
            tp1 = entry - ATR_TP1_MULT * atr
            tp2 = entry - ATR_TP2_MULT * atr
            tp3 = entry - ATR_TP3_MULT * atr

            if tp2 >= tp1:
                tp2 = tp1 - tick
            if tp3 >= tp2:
                tp3 = tp2 - tick

        # R:R based on TP1
        risk = abs(entry - sl)
        reward = abs(tp1 - entry)
        rr = round(reward / risk, 2) if risk > 0 else 0

        # ROUNDING & VALIDATION
        fmt_entry = _fmt(entry, decimals)
        fmt_sl = _fmt(sl, decimals)
        fmt_tp1 = _fmt(tp1, decimals)
        fmt_tp2 = _fmt(tp2, decimals)
        fmt_tp3 = _fmt(tp3, decimals)

        levels = {
            "entry": fmt_entry,
            "sl": fmt_sl,
            "tp1": fmt_tp1,
            "tp2": fmt_tp2,
            "tp3": fmt_tp3,
        }

        if any(
            not math.isfinite(v) or v <= 0
            for v in levels.values()
        ):
            continue

        vol_ma = float(latest.get("vol_ma", 0) or 0)
        volume = float(latest.get("volume", 0) or 0)
        vol_ratio = round(volume / vol_ma, 2) if vol_ma > 0 else 0

        leverage = _recommended_leverage(atr, close)
        trend = _trend_direction(
            latest, f"ema{EMA_FAST}", f"ema{EMA_SLOW}"
        )

        signal = {
            "symbol": symbol,
            "direction": direction,
            "signal_type": signal_type or "NORMAL",
            "entry": fmt_entry,
            "sl": fmt_sl,
            "tp1": fmt_tp1,
            "tp2": fmt_tp2,
            "tp3": fmt_tp3,
            "rr": rr,
            "leverage": leverage,
            "trend": trend,
            "score": score,
            "base_score": base_score,
            "pump_bonus_applied": pump_bonus_applied,
            "components": components,
            "pump_dump": pd_result,
            "indicators": {
                "rsi": round(latest.get("rsi") or 0, 2),
                "macd": round(latest.get("macd") or 0, 8),
                "macd_sig": round(latest.get("macd_sig") or 0, 8),
                "macd_hist": round(latest.get("macd_hist") or 0, 8),
                "ema50": _fmt(
                    latest.get(f"ema{EMA_FAST}") or 0, decimals
                ),
                "ema200": _fmt(
                    latest.get(f"ema{EMA_SLOW}") or 0, decimals
                ),
                "atr": round(atr, 6),
                "volume": round(volume, 2),
                "vol_ratio": vol_ratio,
            },
        }

        signals.append(signal)

    return signals
