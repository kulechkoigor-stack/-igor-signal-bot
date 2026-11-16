"""
Trade outcome tracker for IGOR Smart Signals PRO.

Tracks TP1 / TP2 / TP3 / SL / TIMEOUT and records outcomes.
"""

import time
import logging

logger = logging.getLogger(__name__)

TRADE_MAX_AGE = 86_400

# Current trades held in memory.
# One active trade per symbol and direction.
_open_trades = {}


def register(sig: dict) -> None:
    """Register a signal after it has been sent successfully."""

    try:
        symbol = str(sig["symbol"]).strip().upper()
        direction = str(
            sig.get("direction") or sig.get("side") or ""
        ).strip().upper()

        if not symbol or direction not in ("LONG", "SHORT"):
            logger.warning("[TradeTracker] Invalid symbol/direction")
            return

        entry = float(sig["entry"])
        sl = float(sig["sl"])
        tp1 = float(sig["tp1"])
        tp2 = float(sig["tp2"])
        tp3 = float(sig["tp3"])

        values = (entry, sl, tp1, tp2, tp3)

        if not all(value > 0 for value in values):
            logger.warning(
                "[TradeTracker] Invalid price levels for %s", symbol
            )
            return

        if direction == "LONG":
            valid = sl < entry < tp1 < tp2 < tp3
        else:
            valid = tp3 < tp2 < tp1 < entry < sl

        if not valid:
            logger.warning(
                "[TradeTracker] Invalid level ordering for %s %s",
                symbol, direction
            )
            return

        key = f"{symbol}|{direction}"

        if key in _open_trades:
            logger.warning(
                "[TradeTracker] Already tracking %s; new signal not registered",
                key
            )
            return

        _open_trades[key] = {
            "symbol": symbol,
            "direction": direction,
            "entry": entry,
            "sl": sl,
            "tp1": tp1,
            "tp2": tp2,
            "tp3": tp3,
            "score": int(sig.get("score", 0)),
            "rr": float(sig.get("rr") or 0),
            "tp1_hit": False,
            "tp2_hit": False,
            "tp3_hit": False,
            "opened_at": time.time(),
        }

        logger.info("[TradeTracker] Registered %s", key)

    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        logger.error("[TradeTracker] Invalid signal: %s", exc)


def _next_event(trade: dict, price: float):
    """Return the next target event or stop-loss event."""

    if trade["direction"] == "LONG":
        tp1_reached = price >= trade["tp1"]
        tp2_reached = price >= trade["tp2"]
        tp3_reached = price >= trade["tp3"]
        sl_reached = price <= trade["sl"]
    else:
        tp1_reached = price <= trade["tp1"]
        tp2_reached = price <= trade["tp2"]
        tp3_reached = price <= trade["tp3"]
        sl_reached = price >= trade["sl"]

    # If price jumps across several targets, report the furthest one.
    # The statistics trackers infer all preceding TP milestones.
    if tp3_reached and not trade["tp3_hit"]:
        trade["tp1_hit"] = True
        trade["tp2_hit"] = True
        trade["tp3_hit"] = True
        return "TP3"

    if tp2_reached and not trade["tp2_hit"]:
        trade["tp1_hit"] = True
        trade["tp2_hit"] = True
        return "TP2"

    if tp1_reached and not trade["tp1_hit"]:
        trade["tp1_hit"] = True
        return "TP1"

    if sl_reached:
        return "SL"

    return None


def _record_statistics(trade: dict, event: str) -> None:
    """Record each statistics destination independently."""

    try:
        import stats_tracker
        stats_tracker.record_outcome(trade, event)
    except Exception:
        logger.exception(
            "[TradeTracker] stats_tracker recording failed"
        )

    try:
        import stats24_tracker
        stats24_tracker.record_outcome(trade, event)
    except Exception:
        logger.exception(
            "[TradeTracker] stats24_tracker recording failed"
        )


def poll(client) -> None:
    """Check tracked trades against current prices and expiry."""

    if not _open_trades:
        return

    try:
        from telegram_notifier import send_trade_update
    except Exception:
        logger.exception(
            "[TradeTracker] Cannot import Telegram notifier"
        )
        send_trade_update = None

    now = time.time()
    to_drop = []

    for key, trade in list(_open_trades.items()):

        if now - trade["opened_at"] > TRADE_MAX_AGE:
            logger.info("[TradeTracker] Expired %s", key)

            # Record timeout in both statistics trackers before removing it.
            _record_statistics(trade, "TIMEOUT")

            if send_trade_update:
                try:
                    send_trade_update(trade, "TIMEOUT")
                except Exception:
                    logger.exception(
                        "[TradeTracker] Timeout notification failed"
                    )

            to_drop.append(key)
            continue

        try:
            price = client.get_price(trade["symbol"])
            price = float(price) if price is not None else None
        except Exception as exc:
            logger.warning(
                "[TradeTracker] Price fetch failed for %s: %s",
                trade["symbol"], exc
            )
            continue

        if price is None or price <= 0:
            continue

        trade["current_price"] = price
        event = _next_event(trade, price)

        if event is None:
            continue

        logger.info(
            "[TradeTracker] %s — %s at %s", key, event, price
        )

        _record_statistics(trade, event)

        if send_trade_update:
            try:
                send_trade_update(trade, event)
            except Exception:
                logger.exception(
                    "[TradeTracker] Telegram update failed"
                )

        if event in ("TP3", "SL"):
            to_drop.append(key)

    for key in to_drop:
        _open_trades.pop(key, None)
        logger.info("[TradeTracker] Closed %s", key)


def open_count() -> int:
    """Return the number of currently tracked trades."""
    return len(_open_trades)
