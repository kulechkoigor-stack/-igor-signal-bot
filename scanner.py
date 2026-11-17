import logging
import math
from collections import Counter

logger = logging.getLogger(__name__)


# ============================================================
# MARKET HEATMAP
# ============================================================

def _safe_float(value, default=0.0):
    try:
        value = float(value)
        if math.isfinite(value):
            return value
    except (TypeError, ValueError):
        pass

    return default


def _clamp(value, low=0.0, high=100.0):
    return max(low, min(high, value))


def calculate_market_heat(market_data):
    """
    Calculate overall market heat from already scanned 15m data.

    market_data:
        list of dictionaries:
        {
            "symbol": str,
            "direction": "LONG"/"SHORT"/None,
            "score": float,
            "rsi": float,
            "volume_ratio": float,
            "price_change": float,
            "trend": "Bullish"/"Bearish"/"Neutral"
        }

    Returns:
        {
            "heat": 0-100,
            "bias": "LONG"/"SHORT"/"NEUTRAL",
            "bullish_pct": float,
            "bearish_pct": float,
            "volume_score": float,
            "momentum_score": float,
            "trend_score": float
        }
    """

    if not market_data:
        return {
            "heat": 50,
            "bias": "NEUTRAL",
            "bullish_pct": 0,
            "bearish_pct": 0,
            "volume_score": 50,
            "momentum_score": 50,
            "trend_score": 50,
        }

    total = len(market_data)

    bullish = 0
    bearish = 0

    volume_values = []
    momentum_values = []
    trend_values = []

    for item in market_data:

        direction = item.get("direction")

        if direction == "LONG":
            bullish += 1

        elif direction == "SHORT":
            bearish += 1

        # ----------------------------------------------------
        # Volume
        # ----------------------------------------------------

        vol_ratio = _safe_float(
            item.get("volume_ratio")
        )

        volume_score = min(
            100,
            vol_ratio * 30
        )

        volume_values.append(
            volume_score
        )

        # ----------------------------------------------------
        # Momentum
        # ----------------------------------------------------

        price_change = _safe_float(
            item.get("price_change")
        )

        momentum_score = _clamp(
            50 + price_change * 10
        )

        momentum_values.append(
            momentum_score
        )

        # ----------------------------------------------------
        # Trend
        # ----------------------------------------------------

        trend = item.get("trend")

        if trend == "Bullish":
            trend_values.append(100)

        elif trend == "Bearish":
            trend_values.append(0)

        else:
            trend_values.append(50)

    # ========================================================
    # MARKET BREADTH
    # ========================================================

    bullish_pct = (
        bullish / total * 100
    )

    bearish_pct = (
        bearish / total * 100
    )

    breadth_score = (
        50
        + (bullish_pct - bearish_pct) * 0.5
    )

    breadth_score = _clamp(
        breadth_score
    )

    # ========================================================
    # COMPONENT SCORES
    # ========================================================

    volume_score = (
        sum(volume_values) / len(volume_values)
        if volume_values
        else 50
    )

    momentum_score = (
        sum(momentum_values) / len(momentum_values)
        if momentum_values
        else 50
    )

    trend_score = (
        sum(trend_values) / len(trend_values)
        if trend_values
        else 50
    )

    # ========================================================
    # FINAL HEAT
    # ========================================================

    heat = (
        breadth_score * 0.40
        + momentum_score * 0.25
        + trend_score * 0.20
        + volume_score * 0.15
    )

    heat = int(
        round(
            _clamp(heat)
        )
    )

    # ========================================================
    # MARKET BIAS
    # ========================================================

    if heat >= 65:
        bias = "LONG"

    elif heat <= 35:
        bias = "SHORT"

    else:
        bias = "NEUTRAL"

    result = {
        "heat": heat,
        "bias": bias,
        "bullish_pct": round(
            bullish_pct,
            1
        ),
        "bearish_pct": round(
            bearish_pct,
            1
        ),
        "volume_score": round(
            volume_score,
            1
        ),
        "momentum_score": round(
            momentum_score,
            1
        ),
        "trend_score": round(
            trend_score,
            1
        ),
    }

    logger.info(
        "🔥 MARKET HEAT | "
        f"heat={heat}/100 | "
        f"bias={bias} | "
        f"bullish={bullish_pct:.1f}% | "
        f"bearish={bearish_pct:.1f}% | "
        f"momentum={momentum_score:.1f} | "
        f"trend={trend_score:.1f} | "
        f"volume={volume_score:.1f}"
    )

    return result


# ============================================================
# SIGNAL ALIGNMENT
# ============================================================

def heat_alignment(
    heat_data,
    direction
):
    """
    Calculate how strongly the signal agrees
    with the current market heat.

    Returns:
        -10 ... +10
    """

    if not heat_data:
        return 0

    heat = _safe_float(
        heat_data.get("heat"),
        50
    )

    bias = heat_data.get(
        "bias",
        "NEUTRAL"
    )

    if direction == "LONG":

        if bias == "LONG":

            if heat >= 80:
                return 10

            if heat >= 70:
                return 7

            return 4

        if bias == "SHORT":

            if heat <= 20:
                return -10

            if heat <= 30:
                return -7

            return -4

    elif direction == "SHORT":

        if bias == "SHORT":

            if heat <= 20:
                return 10

            if heat <= 30:
                return 7

            return 4

        if bias == "LONG":

            if heat >= 80:
                return -10

            if heat >= 70:
                return -7

            return -4

    return 0
