import logging
import math
from html import escape

import requests

import stats24_tracker
import stats_tracker
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
from market_analysis import get_market_analysis

logger = logging.getLogger(__name__)
_BASE_URL = "https://api.telegram.org/bot{token}/sendMessage"


def _clean_symbol(symbol: str) -> str:
    return str(symbol or "UNKNOWN").replace("-USDT-SWAP", "USDT").replace("-", "").replace(":", "")


def _finite_float(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _format_price(value):
    number = _finite_float(value)
    if number is None:
        return "н/д"
    if number == 0:
        return "0"
    places = 2 if abs(number) >= 1 else min(10, max(4, 3 - math.floor(math.log10(abs(number)))))
    return f"{number:,.{places}f}".rstrip("0").rstrip(".")


def _format_metric(value, places=2, suffix=""):
    number = _finite_float(value)
    return "н/д" if number is None else f"{number:,.{places}f}{suffix}"


def format_message(signal: dict) -> str:
    direction = str(signal.get("direction", "UNKNOWN")).upper()
    symbol = escape(_clean_symbol(signal.get("symbol")))
    indicators = signal.get("indicators")
    indicators = indicators if isinstance(indicators, dict) else {}
    score = int(_finite_float(signal.get("score")) or 0)
    grade = signal.get("grade")
    if grade not in {"A+", "A", "B", "C", "F"}:
        grade = "A+" if score >= 85 else "A" if score >= 75 else "B" if score >= 65 else "C"

    badges = {"A+": "🔥", "A": "🟢", "B": "🟡", "C": "⚪", "F": "⚪"}
    signal_type = escape(str(signal.get("signal_type", "NORMAL")))
    pump_dump = signal.get("pump_dump")
    pump_dump = pump_dump if isinstance(pump_dump, dict) else {}
    sep = "────────────────────"
    emoji = "🟢 LONG" if direction == "LONG" else "🔴 SHORT" if direction == "SHORT" else "⚪ NEUTRAL"

    trend = str(signal.get("trend") or "Neutral")
    trend_display = {
        "bullish": "📈 Висхідний", "bearish": "📉 Низхідний",
        "neutral": "➡️ Нейтральний",
    }.get(trend.lower(), escape(trend))

    rvol = pump_dump.get("rvol")
    if rvol is None:
        rvol = signal.get("rvol", signal.get("vol_ratio"))
    rvol_text = _format_metric(rvol, 2 if pump_dump.get("rvol") is not None else 1, "× Avg")

    rr = _finite_float(signal.get("rr"))
    if rr is None:
        entry_num, sl_num, tp2_num = map(
            _finite_float, (signal.get("entry"), signal.get("sl"), signal.get("tp2"))
        )
        risk = abs(entry_num - sl_num) if entry_num is not None and sl_num is not None else 0
        rr = round(abs(tp2_num - entry_num) / risk, 2) if risk and tp2_num is not None and entry_num is not None else None

    leverage = _finite_float(signal.get("leverage"))
    leverage_text = f"{leverage:g}×" if leverage is not None else "10×"

    impulse = ""
    if pump_dump.get("confirmed"):
        impulse = "\n🚀 <b>Імпульс PUMP</b>" if pump_dump.get("pump") else "\n💥 <b>Імпульс DUMP</b>"

    message = (
        f"🚨 <b>SIGNAL DETECTED</b> 🚨\n\n"
        f"<b>{badges[grade]} GRADE {escape(grade)}</b> · <code>{score}/100</code>\n"
        f"<b>{emoji} · {symbol}</b> (Плече: <code>{leverage_text}</code>)\n"
        f"<i>Стратегія: {signal_type}</i>\n{sep}\n"
        f"🎯 <b>ПЛАН УГОДИ:</b>\n"
        f"├ Вхід: <code>{_format_price(signal.get('entry'))}</code>\n"
        f"├ TP1:   <code>{_format_price(signal.get('tp1'))}</code>\n"
        f"├ TP2:   <code>{_format_price(signal.get('tp2'))}</code>\n"
        f"├ TP3:   <code>{_format_price(signal.get('tp3'))}</code>\n"
        f"├ Стоп:  <code>{_format_price(signal.get('sl'))}</code>\n"
        f"└ R:R:   <code>1:{_format_metric(rr, 2)}</code>\n{sep}\n"
        f"📊 <b>МЕТРИКИ СИГНАЛУ:</b>\n"
        f"├ Тренд: {trend_display}\n"
        f"├ RVOL: <code>{rvol_text}</code>\n"
        f"└ RSI (14): <code>{_format_metric(indicators.get('rsi'), 1)}</code>"
        f"{impulse}\n{sep}\n"
    )

    if score < 75:
        message += "⚠️ <i>Підвищений ризик. Перевірте підтвердження об’ємом.</i>\n\n"

    try:
        response = requests.get(
            "https://www.okx.com/api/v5/market/candles",
            params={"instId": signal["symbol"], "bar": "15m", "limit": "30"},
            timeout=5,
        )
        response.raise_for_status()
        market = get_market_analysis(signal["symbol"], response.json().get("data", []))
        signal["market_analysis"] = dict(market)
        funding = market.get("funding")
        oi = market.get("oi")
        buy, sell = market.get("buy"), market.get("sell")

        message += (
            "🌐 <b>OKX КОНТЕКСТ:</b>\n"
            f"├ Funding: <code>{f'{funding:.4f}%' if funding is not None else 'N/A'}</code>\n"
            f"├ OI: <code>{f'{oi:,.0f} USDT' if oi is not None else 'N/A'}</code>\n"
            f"└ Стакан: {f'🟢 {buy:.1f}% / 🔴 {sell:.1f}%' if buy is not None and sell is not None else 'N/A'}\n{sep}\n"
        )
    except Exception as exc:
        logger.warning("Market analysis unavailable for %s: %s", signal.get("symbol", "unknown"), exc)

    return message + "💡 <i>Дотримуйтесь ризик-менеджменту: 1–2% на угоду.</i>"


def send_signal(signal: dict) -> bool:
    if not TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN is not set — cannot send message")
        return False

    try:
        response = requests.post(
            _BASE_URL.format(token=TELEGRAM_BOT_TOKEN),
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": format_message(signal),
                "parse_mode": "HTML",
            },
            timeout=10,
        )
        response.raise_for_status()
        result = response.json()
        if not result.get("ok", False):
            logger.error(
                "Telegram did not confirm signal delivery for %s: %s",
                signal.get("symbol"),
                result,
            )
            return False
    except requests.RequestException as exc:
        logger.error("Telegram request failed for %s: %s", signal.get("symbol", "unknown"), exc)
        return False
    except ValueError as exc:
        logger.error("Invalid Telegram response for %s: %s", signal.get("symbol", "unknown"), exc)
        return False
    except Exception:
        logger.exception("Unexpected error while sending signal for %s", signal.get("symbol", "unknown"))
        return False

    logger.info(
        "Telegram accepted %s signal for %s (score %s)",
        signal.get("direction"),
        signal.get("symbol"),
        signal.get("score"),
    )

    try:
        stats_tracker.record_signal(signal)
    except Exception:
        logger.exception("stats_tracker.record_signal failed for %s", signal.get("symbol", "unknown"))

    try:
        stats24_tracker.record_signal(signal)
    except Exception:
        logger.exception("stats24_tracker.record_signal failed for %s", signal.get("symbol", "unknown"))

    return True


def send_trade_update(trade: dict, event: str) -> bool:
    if not TELEGRAM_BOT_TOKEN:
        return False

    symbol = _clean_symbol(trade.get("symbol"))
    direction = trade.get("direction", "").upper()
    entry = _finite_float(trade.get("entry"))
    current_price = _finite_float(trade.get("current_price") or trade.get("price"))

    profit_str = ""
    if entry and current_price:
        pct = ((current_price - entry) / entry) * 100 if direction == "LONG" else ((entry - current_price) / entry) * 100
        profit_str = f"\n📈 Прибуток: <code>+{pct:.2f}%</code>" if pct > 0 else f"\n📉 Результат: <code>{pct:.2f}%</code>"

    labels = {
        "TP1": ("✅", f"<b>{symbol} — {direction}</b>\n<b>TAKE PROFIT 1 REACHED</b> 🎯{profit_str}"),
        "TP2": ("🚀", f"<b>{symbol} — {direction}</b>\n<b>TAKE PROFIT 2 REACHED</b> 🚀{profit_str}"),
        "TP3": ("🏆", f"<b>{symbol} — {direction}</b>\n<b>ALL TARGETS HIT (TP3)</b> 🔥{profit_str}"),
        "SL": ("🛑", f"<b>{symbol} — {direction}</b>\n<b>STOP LOSS TRIGGERED</b> ❌{profit_str}"),
        "TP2_TIMEOUT": ("⏳", f"<b>{symbol} — {direction}</b>\n<b>TIMEOUT (TP2 Hit)</b> 🎯"),
        "TP1_TIMEOUT": ("⏳", f"<b>{symbol} — {direction}</b>\n<b>TIMEOUT (TP1 Hit)</b> 🎯"),
        "TIMEOUT": ("⏳", f"<b>{symbol} — {direction}</b>\n<b>TRADE TIMEOUT EXPIRED</b>"),
    }

    if event not in labels:
        logger.warning("Unknown trade update event: %s", event)
        return False

    emoji, body = labels[event]
    try:
        response = requests.post(
            _BASE_URL.format(token=TELEGRAM_BOT_TOKEN),
            json={"chat_id": TELEGRAM_CHAT_ID, "text": f"{emoji} {body}", "parse_mode": "HTML"},
            timeout=10,
        )
        response.raise_for_status()
        return True
    except Exception as exc:
        logger.error("Telegram trade update error: %s", exc)
        return False


def send_startup_message() -> None:
    if TELEGRAM_BOT_TOKEN:
        try:
            requests.post(
                _BASE_URL.format(token=TELEGRAM_BOT_TOKEN),
                json={"chat_id": TELEGRAM_CHAT_ID, "text": "🤖 <b>Signal Bot успішно запущено та оптимізовано!</b>", "parse_mode": "HTML"},
                timeout=10,
            )
        except Exception as exc:
            logger.warning("Could not send startup message: %s", exc)


def send_daily_report() -> None:
    if not TELEGRAM_BOT_TOKEN:
        return
    try:
        response = requests.post(
            _BASE_URL.format(token=TELEGRAM_BOT_TOKEN),
            json={"chat_id": TELEGRAM_CHAT_ID, "text": stats24_tracker.format_stats()},
            timeout=10,
        )
        response.raise_for_status()
    except Exception as exc:
        logger.error("Telegram daily report error: %s", exc)


def send_error_alert(message: str) -> None:
    if not TELEGRAM_BOT_TOKEN:
        return
    try:
        requests.post(
            _BASE_URL.format(token=TELEGRAM_BOT_TOKEN),
            json={"chat_id": TELEGRAM_CHAT_ID, "text": f"⚠️ <b>Bot Alert:</b> {escape(message)}", "parse_mode": "HTML"},
            timeout=10,
        )
    except Exception as exc:
        logger.warning("Could not send error alert: %s", exc)
