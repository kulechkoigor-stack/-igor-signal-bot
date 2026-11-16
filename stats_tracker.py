"""
Trade statistics tracker.

Stores daily and all-time statistics in stats.json.

Each trade is tracked individually, so:
- TP1/TP2/TP3 are stages of ONE trade
- Win Rate is based on final TP3 vs SL
- Average R:R is calculated from actual sent signals
- Daily statistics reset automatically when the date changes
- TIMEOUT is tracked separately and is neither a win nor a loss
"""

import json
import os
import logging
from threading import Lock
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

_STATS_FILE = os.path.join(os.path.dirname(__file__), "stats.json")
_lock = Lock()

_DEFAULTS = {
    "date": "",

    # Daily
    "total_signals": 0,
    "strong_signals": 0,
    "watchlist_signals": 0,

    "tp1_hits": 0,
    "tp2_hits": 0,
    "tp3_hits": 0,
    "sl_hits": 0,
    "timeout_hits": 0,

    "score_sum": 0.0,
    "rr_sum": 0.0,

    # Currently tracked trades
    "trades": {},

    # All-time statistics
    "all_time": {
        "total_signals": 0,
        "strong_signals": 0,
        "watchlist_signals": 0,
        "tp1_hits": 0,
        "tp2_hits": 0,
        "tp3_hits": 0,
        "sl_hits": 0,
        "timeout_hits": 0,
        "score_sum": 0.0,
        "rr_sum": 0.0,
    },
}

_cache = {}


# ── Date ──────────────────────────────────────────────────────────────────────

def _today() -> str:
    """UTC date used for Daily Report."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


# ── I/O ───────────────────────────────────────────────────────────────────────

def _load() -> dict:
    try:
        with open(_STATS_FILE, "r", encoding="utf-8") as fh:
            data = json.load(fh)

        if not isinstance(data, dict):
            logger.warning(
                "[StatsTracker] Invalid stats.json structure — starting fresh"
            )
            return _new_stats()

        # Detect old stats.json format.
        if "all_time" not in data or "trades" not in data:
            logger.warning(
                "[StatsTracker] Old stats.json format detected — "
                "starting new statistics"
            )
            return _new_stats()

        # Fill missing top-level defaults without overwriting saved values.
        for key, value in _DEFAULTS.items():
            if key not in data:
                data[key] = value.copy() if isinstance(value, dict) else value

        # Fill missing all-time fields, including timeout_hits for older files.
        if not isinstance(data.get("all_time"), dict):
            data["all_time"] = dict(_DEFAULTS["all_time"])

        for key, value in _DEFAULTS["all_time"].items():
            data["all_time"].setdefault(key, value)

        if not isinstance(data.get("trades"), dict):
            data["trades"] = {}

        return data

    except FileNotFoundError:
        return _new_stats()

    except (json.JSONDecodeError, OSError) as exc:
        logger.error(
            f"[StatsTracker] Could not read stats.json ({exc}) — "
            "starting fresh"
        )
        return _new_stats()


def _new_stats() -> dict:
    data = dict(_DEFAULTS)
    data["date"] = _today()
    data["trades"] = {}
    data["all_time"] = dict(_DEFAULTS["all_time"])
    return data


def _save(data: dict) -> None:
    try:
        tmp_file = _STATS_FILE + ".tmp"

        with open(tmp_file, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)

        os.replace(tmp_file, _STATS_FILE)

    except Exception as exc:
        logger.error(
            f"[StatsTracker] Failed to save stats.json: {exc}"
        )


# ── Daily reset ───────────────────────────────────────────────────────────────

def _reset_if_new_day(s: dict) -> None:
    today = _today()

    if s.get("date") == today:
        return

    logger.info(
        f"[StatsTracker] New day detected: "
        f"{s.get('date')} → {today}"
    )

    s["date"] = today

    s["total_signals"] = 0
    s["strong_signals"] = 0
    s["watchlist_signals"] = 0

    s["tp1_hits"] = 0
    s["tp2_hits"] = 0
    s["tp3_hits"] = 0
    s["sl_hits"] = 0
    s["timeout_hits"] = 0

    s["score_sum"] = 0.0
    s["rr_sum"] = 0.0

    # Old unfinished trades must not contaminate the new day's statistics.
    s["trades"] = {}


# ── Cache ─────────────────────────────────────────────────────────────────────

def _get() -> dict:
    global _cache

    if not _cache:
        _cache = _load()

        logger.info(
            f"[StatsTracker] Loaded stats.json — "
            f"date={_cache['date']}  "
            f"signals={_cache['total_signals']}  "
            f"tp3={_cache['tp3_hits']}  "
            f"sl={_cache['sl_hits']}"
        )

    _reset_if_new_day(_cache)
    return _cache


# ── Signal registration ───────────────────────────────────────────────────────

def record_signal(signal: dict) -> None:
    """Record a newly sent signal."""

    symbol = str(signal.get("symbol", "")).upper().strip()
    direction = str(
        signal.get("direction") or signal.get("side") or ""
    ).upper().strip()

    if not symbol or not direction:
        logger.warning(
            "[StatsTracker] Signal has no symbol/direction — ignored"
        )
        return

    key = f"{symbol}|{direction}"

    try:
        sc = int(signal.get("score", 0))
    except (TypeError, ValueError):
        sc = 0

    try:
        rr = float(signal.get("rr") or 0)
    except (TypeError, ValueError):
        rr = 0.0

    trade = {
        "symbol": symbol,
        "direction": direction,
        "score": sc,
        "rr": rr,
        "tp1_hit": False,
        "tp2_hit": False,
        "tp3_hit": False,
        "sl_hit": False,
    }

    with _lock:
        s = _get()

        s["total_signals"] += 1

        if sc >= 80:
            s["strong_signals"] += 1
        elif sc >= 75:
            s["watchlist_signals"] += 1

        s["score_sum"] += sc
        if rr > 0:
            s["rr_sum"] += rr

        # Note: the existing registry uses symbol|direction as its key.
        # A new signal for the same pair/direction replaces that registry entry.
        s["trades"][key] = trade

        a = s["all_time"]
        a["total_signals"] += 1

        if sc >= 80:
            a["strong_signals"] += 1
        elif sc >= 75:
            a["watchlist_signals"] += 1

        a["score_sum"] += sc
        if rr > 0:
            a["rr_sum"] += rr

        _save(s)

    logger.info(
        f"[StatsTracker] Signal recorded — {key}  score={sc}  rr={rr}"
    )


# ── Outcome registration ──────────────────────────────────────────────────────

def record_outcome(trade: dict, event: str) -> None:
    """
    Record TP milestones and final outcomes for one tracked trade.

    TP2 implies TP1 was reached; TP3 implies TP1 and TP2 were reached.
    Each milestone is counted at most once per tracked trade.
    TIMEOUT is tracked separately and is neither a win nor a loss.
    """

    symbol = str(trade.get("symbol", "")).upper().strip()
    direction = str(
        trade.get("direction") or trade.get("side") or ""
    ).upper().strip()

    if not symbol or not direction:
        logger.warning(
            "[StatsTracker] Outcome has no symbol/direction — ignored"
        )
        return

    key = f"{symbol}|{direction}"
    event = str(event).upper().strip()

    if event not in ("TP1", "TP2", "TP3", "SL", "TIMEOUT"):
        logger.warning(
            f"[StatsTracker] Unknown event '{event}' — ignored"
        )
        return

    with _lock:
        s = _get()
        tracked = s["trades"].get(key)

        if tracked is None:
            logger.warning(
                f"[StatsTracker] Trade not found: {key} — event={event}"
            )
            return

        # Keep older trade records compatible with missing flags.
        for flag in ("tp1_hit", "tp2_hit", "tp3_hit", "sl_hit"):
            tracked.setdefault(flag, False)

        if event in ("TP1", "TP2", "TP3"):
            milestones = {
                "TP1": ("tp1_hit",),
                "TP2": ("tp1_hit", "tp2_hit"),
                "TP3": ("tp1_hit", "tp2_hit", "tp3_hit"),
            }

            for flag in milestones[event]:
                if not tracked.get(flag, False):
                    tracked[flag] = True
                    counter = flag.replace("_hit", "_hits")
                    s[counter] = s.get(counter, 0) + 1
                    s["all_time"][counter] = (
                        s["all_time"].get(counter, 0) + 1
                    )

            if event == "TP3":
                # TP3 is the final winning outcome.
                s["trades"].pop(key, None)

        elif event == "SL":
            if tracked.get("sl_hit", False):
                return

            tracked["sl_hit"] = True
            s["sl_hits"] += 1
            s["all_time"]["sl_hits"] += 1
            # SL is the final losing outcome.
            s["trades"].pop(key, None)

        elif event == "TIMEOUT":
            # Timeout is not a win or a loss.
            s["timeout_hits"] = s.get("timeout_hits", 0) + 1
            s["all_time"]["timeout_hits"] = (
                s["all_time"].get("timeout_hits", 0) + 1
            )
            s["trades"].pop(key, None)

        _save(s)

    logger.info(f"[StatsTracker] Outcome recorded — {key} → {event}")


# ── Statistics ────────────────────────────────────────────────────────────────

def _calculate(s: dict) -> dict:
    """Calculate statistics from the current daily counters."""

    # Final outcomes only; TIMEOUT is excluded from win-rate calculation.
    closed = s["tp3_hits"] + s["sl_hits"]

    win_rate = (
        s["tp3_hits"] / closed * 100
        if closed > 0
        else 0.0
    )

    avg_score = (
        s["score_sum"] / s["total_signals"]
        if s["total_signals"] > 0
        else 0.0
    )

    avg_rr = (
        s["rr_sum"] / s["total_signals"]
        if s["total_signals"] > 0
        else 0.0
    )

    return {
        "total_signals": s["total_signals"],
        "strong_signals": s["strong_signals"],
        "watchlist_signals": s["watchlist_signals"],
        "tp1_hits": s["tp1_hits"],
        "tp2_hits": s["tp2_hits"],
        "tp3_hits": s["tp3_hits"],
        "sl_hits": s["sl_hits"],
        "timeout_hits": s.get("timeout_hits", 0),
        "win_rate": win_rate,
        "avg_score": avg_score,
        "avg_rr": avg_rr,
    }


def get_stats() -> dict:
    """Return today's statistics."""
    with _lock:
        s = _get()
        return _calculate(s)


def get_all_time_stats() -> dict:
    """Return all-time statistics."""

    with _lock:
        s = _get()
        a = s["all_time"]

        closed = a["tp3_hits"] + a["sl_hits"]

        win_rate = (
            a["tp3_hits"] / closed * 100
            if closed > 0
            else 0.0
        )

        avg_score = (
            a["score_sum"] / a["total_signals"]
            if a["total_signals"] > 0
            else 0.0
        )

        avg_rr = (
            a["rr_sum"] / a["total_signals"]
            if a["total_signals"] > 0
            else 0.0
        )

        return {
            "total_signals": a["total_signals"],
            "strong_signals": a["strong_signals"],
            "watchlist_signals": a["watchlist_signals"],
            "tp1_hits": a["tp1_hits"],
            "tp2_hits": a["tp2_hits"],
            "tp3_hits": a["tp3_hits"],
            "sl_hits": a["sl_hits"],
            "timeout_hits": a.get("timeout_hits", 0),
            "win_rate": win_rate,
            "avg_score": avg_score,
            "avg_rr": avg_rr,
        }
