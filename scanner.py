import time
import logging

from market_heatmap import calculate_market_heat
from binance_client import BinanceClient
from indicators import calculate_indicators
from signal_generator import generate_signals
from telegram_notifier import send_signal

from config import (
    TOP_N_PAIRS,
    SIGNAL_COOLDOWN,
    MIN_SCORE_NORMAL,
    MIN_SCORE_PUMP_DUMP,
    EMA_FAST,
    EMA_SLOW,
    MIN_ATR_PERCENT,
    COIN_SIGNAL_COOLDOWN,
    STABLECOIN_PAIRS,
)

import trade_tracker


logger = logging.getLogger(__name__)

_sent_at: dict[str, float] = {}
_coin_sent_at: dict[str, float] = {}


def _cooldown_ok(key: str, now: float) -> bool:
    return (now - _sent_at.get(key, 0)) >= SIGNAL_COOLDOWN


def _coin_rotation_ok(symbol: str, now: float) -> bool:
    return (now - _coin_sent_at.get(symbol, 0)) >= COIN_SIGNAL_COOLDOWN


def _safe_float(value, default=0.0) -> float:
    try:
        result = float(value)
        return (
            result
            if result == result and abs(result) != float("inf")
            else default
        )
    except (TypeError, ValueError):
        return default


def _log_trade_flow(client, symbol: str, direction: str) -> None:
    """
    Лише діагностика потоку угод.
    Не блокує сигнал і не гарантує майбутній напрямок ціни.
    """
    try:
        flow = client.get_trade_flow(symbol, limit=100)

        if not flow or not flow.get("available"):
            logger.info(
                "[%s] FLOW | дані потоку угод недоступні",
                symbol,
            )
            return

        imbalance = _safe_float(flow.get("imbalance_pct"))

        if imbalance >= 15:
            flow_bias = "BUYERS"
        elif imbalance <= -15:
            flow_bias = "SELLERS"
        else:
            flow_bias = "MIXED"

        if direction == "LONG" and imbalance <= -15:
            warning = "⚠️ LONG проти потоку продажів"
        elif direction == "SHORT" and imbalance >= 15:
            warning = "⚠️ SHORT проти потоку покупок"
        else:
            warning = "помітного конфлікту немає"

        logger.info(
            "[%s] FLOW | signal=%s | imbalance=%+.2f%% | "
            "bias=%s | buy_volume=%s | sell_volume=%s | "
            "trades=%s | %s",
            symbol,
            direction,
            imbalance,
            flow_bias,
            flow.get("buy_volume", 0),
            flow.get("sell_volume", 0),
            flow.get("trades", 0),
            warning,
        )

    except Exception as exc:
        logger.warning(
            "[%s] Помилка діагностики FLOW: %s",
            symbol,
            exc,
        )


def run_scan(client: BinanceClient) -> int:
    logger.info("========== СКАНУВАННЯ ПОЧАТО ==========")

    try:
        pairs = client.get_top_pairs(n=TOP_N_PAIRS)
    except Exception as exc:
        logger.error(
            "Не вдалося отримати список пар: %s",
            exc,
            exc_info=True,
        )
        return 0

    if not pairs:
        logger.warning(
            "Пари не отримані. Перевір доступність публічного API OKX."
        )
        return 0

    now = time.time()

    alert_count = 0
    error_count = 0
    generated = 0
    rejected_score = 0
    rejected_rr = 0
    rejected_cooldown = 0
    rejected_policy = 0
    rejected_invalid = 0
    rejected_telegram = 0
    insufficient_data = 0
    rejected_trend = 0

    score_values = []
    market_data = []

    for idx, symbol in enumerate(pairs, start=1):
        try:
            df = client.get_ohlcv(symbol)

            if df is None or len(df) < 250:
                insufficient_data += 1
                logger.debug(
                    "[%s] Пропуск: недостатньо свічок",
                    symbol,
                )
                continue

            try:
                oi_change = client.get_oi_change_pct(symbol)
                df.loc[df.index[-1], "oi_change_pct"] = oi_change
            except Exception as exc:
                logger.debug("[%s] Помилка OI: %s", symbol, exc)

            df = calculate_indicators(df)

            # Дані для теплової карти
            try:
                latest = df.iloc[-1]
                close_now = _safe_float(latest.get("close"))
                close_3ago = _safe_float(df.iloc[-4].get("close"))
                volume = _safe_float(latest.get("volume"))
                vol_ma = _safe_float(latest.get("vol_ma"))

                price_change = (
                    ((close_now - close_3ago) / close_3ago) * 100
                    if close_3ago > 0
                    else 0.0
                )
                volume_ratio = volume / vol_ma if vol_ma > 0 else 0.0

                ema_fast = _safe_float(
                    latest.get(f"ema{EMA_FAST}")
                )
                ema_slow = _safe_float(
                    latest.get(f"ema{EMA_SLOW}")
                )

                if close_now > ema_fast > ema_slow:
                    trend, heat_direction = "Bullish", "LONG"
                elif close_now < ema_fast < ema_slow:
                    trend, heat_direction = "Bearish", "SHORT"
                else:
                    trend, heat_direction = "Neutral", None

                market_data.append({
                    "symbol": symbol,
                    "direction": heat_direction,
                    "score": 0,
                    "rsi": _safe_float(latest.get("rsi")),
                    "volume_ratio": volume_ratio,
                    "price_change": price_change,
                    "trend": trend,
                })

            except Exception as exc:
                logger.debug(
                    "[%s] Помилка даних heatmap: %s",
                    symbol,
                    exc,
                )

            # Генерація сигналів і діагностика score
            stats = {}
            signals = generate_signals(symbol, df, _stats=stats)

            raw_count = int(stats.get("raw", 0) or 0)
            generated += raw_count
            rejected_score += int(
                stats.get("rejected_score", 0) or 0
            )
            rejected_trend += int(
                stats.get("rejected_trend", 0) or 0
            )

            candidates = stats.get("candidates", [])

            for candidate in candidates:
                score = _safe_float(candidate.get("score"))
                required = _safe_float(candidate.get("min_required"))
                score_values.append(score)

                logger.info(
                    "[%s] SCORE | %s | отримано=%.1f | потрібно=%.1f | "
                    "різниця=%+.1f | pump_dump=%s",
                    candidate.get("symbol", symbol),
                    candidate.get("direction", "?"),
                    score,
                    required,
                    score - required,
                    candidate.get("confirmed", False),
                )

            if not signals:
                logger.debug(
                    "[%s] Сигналів немає; перевірено кандидатів=%s",
                    symbol,
                    raw_count,
                )
                continue

            for sig in signals:
                direction = str(
                    sig.get("direction", "UNKNOWN")
                ).upper()

                # Назви інструментів OKX мають формат BTC-USDT-SWAP.
                # Перевірка нижче також підтримує старий формат BTCUSDT.
                normalized_symbol = (
                    symbol.upper()
                    .replace("-", "")
                    .replace("_", "")
                )
                blocked_symbols = {
                    str(item).upper().replace("-", "").replace("_", "")
                    for item in STABLECOIN_PAIRS
                }

                if (
                    symbol.upper() in STABLECOIN_PAIRS
                    or normalized_symbol in blocked_symbols
                ):
                    rejected_policy += 1
                    logger.info(
                        "[%s] Відхилено: стейблкоїн у списку блокування",
                        symbol,
                    )
                    continue

                key = f"{symbol}|{direction}"

                score = _safe_float(sig.get("score"))
                rr = _safe_float(sig.get("rr"))

                pump_dump = sig.get("pump_dump") or {}
                is_pump_dump = bool(
                    pump_dump.get("confirmed", False)
                )

                min_score = (
                    MIN_SCORE_PUMP_DUMP
                    if is_pump_dump
                    else MIN_SCORE_NORMAL
                )

                logger.info(
                    "[%s] ПЕРЕВІРКА | score=%.1f/%.1f | R:R=%.2f | "
                    "pump_dump=%s",
                    key,
                    score,
                    min_score,
                    rr,
                    is_pump_dump,
                )

                # Діагностика потоку угод. Не блокує сигнал.
                _log_trade_flow(client, symbol, direction)

                if not _coin_rotation_ok(symbol, now):
                    rejected_cooldown += 1
                    logger.info(
                        "[%s] Відхилено: cooldown монети",
                        key,
                    )
                    continue

                if not _cooldown_ok(key, now):
                    rejected_cooldown += 1
                    logger.info(
                        "[%s] Відхилено: cooldown напрямку",
                        key,
                    )
                    continue

                if rr < 1.6:
                    rejected_rr += 1
                    logger.info(
                        "[%s] Відхилено: R:R %.2f < 1.6",
                        key,
                        rr,
                    )
                    continue

                if score < min_score:
                    rejected_policy += 1
                    logger.info(
                        "[%s] Відхилено повторним score-фільтром: "
                        "%.1f < %.1f",
                        key,
                        score,
                        min_score,
                    )
                    continue

                try:
                    entry = float(sig["entry"])
                    atr = float(sig["indicators"]["atr"])
                except (TypeError, ValueError, KeyError):
                    rejected_invalid += 1
                    logger.warning(
                        "[%s] Відхилено: некоректні entry або ATR",
                        key,
                    )
                    continue

                if entry <= 0 or atr <= 0:
                    rejected_invalid += 1
                    logger.warning(
                        "[%s] Відхилено: entry або ATR не додатні",
                        key,
                    )
                    continue

                atr_percent = (atr / entry) * 100

                if atr_percent < MIN_ATR_PERCENT:
                    rejected_policy += 1
                    logger.info(
                        "[%s] Відхилено: ATR %.3f%% < %.3f%%",
                        key,
                        atr_percent,
                        MIN_ATR_PERCENT,
                    )
                    continue

                signal_type = (
                    "🚀 PUMP"
                    if is_pump_dump and direction == "LONG"
                    else "📉 DUMP"
                    if is_pump_dump and direction == "SHORT"
                    else "NORMAL"
                )

                logger.info(
                    "СИГНАЛ ДОЗВОЛЕНО | %s %s | score=%.1f | "
                    "R:R=1:%.2f | ATR=%.3f%% | тип=%s",
                    direction,
                    symbol,
                    score,
                    rr,
                    atr_percent,
                    signal_type,
                )

                # Спробуємо надіслати в Telegram (ми не блокуємо трекер, якщо тут помилка)
                try:
                    result = send_signal(sig)
                    logger.info(
                        "[%s] Результат Telegram: %s",
                        key,
                        result,
                    )
                except Exception as exc:
                    rejected_telegram += 1
                    logger.error(
                        "[%s] Помилка Telegram: %s",
                        key,
                        exc,
                        exc_info=True,
                    )

                # ГАРАНТОВАНА РЕЄСТРАЦІЯ В ТРЕКЕРІ НЕЗАЛЕЖНО ВІД TELEGRAM
                sent_time = time.time()
                _sent_at[key] = sent_time
                _coin_sent_at[symbol] = sent_time
                alert_count += 1

                try:
                    registered = trade_tracker.register(sig)
                    logger.info("[%s] Статус реєстрації в trade_tracker: %s (ID: %s)", key, registered, sig.get("trade_id"))
                except Exception as exc:
                    logger.error(
                        "[%s] Помилка реєстрації угоди: %s",
                        key,
                        exc,
                        exc_info=True,
                    )

        except Exception as exc:
            error_count += 1
            logger.error(
                "Помилка обробки %s: %s",
                symbol,
                exc,
                exc_info=True,
            )

        if idx % 10 == 0:
            logger.info(
                "Прогрес сканування: %s/%s",
                idx,
                len(pairs),
            )
            time.sleep(0.3)

    # Теплова карта ринку — поки що лише інформаційна
    try:
        heat_data = calculate_market_heat(market_data)
        logger.info(
            "MARKET HEATMAP | Heat=%s/100 | Bias=%s | Bullish=%.1f%% | "
            "Bearish=%.1f%% | Momentum=%.1f | Trend=%.1f | Volume=%.1f",
            heat_data["heat"],
            heat_data["bias"],
            heat_data["bullish_pct"],
            heat_data["bearish_pct"],
            heat_data["momentum_score"],
            heat_data["trend_score"],
            heat_data["volume_score"],
        )
    except Exception as exc:
        logger.error(
            "Помилка market heatmap: %s",
            exc,
            exc_info=True,
        )

    # Підсумок балів
    if score_values:
        avg_score = sum(score_values) / len(score_values)
        min_seen = min(score_values)
        max_seen = max(score_values)
    else:
        avg_score = min_seen = max_seen = 0.0

    logger.info(
        "\n========== ПІДСУМОК СКАНУВАННЯ ==========\n"
        "Пар у списку:                    %s\n"
        "Недостатньо свічок:              %s\n"
        "Перевірено напрямків:            %s\n"
        "Відхилено генератором за score:  %s\n"
        "Відхилено фільтром тренду:       %s\n"
        "Відхилено за R:R < 1.6:          %s\n"
        "Відхилено через cooldown:        %s\n"
        "Відхилено іншими фільтрами:      %s\n"
        "Некоректні сигнали:              %s\n"
        "Помилки Telegram:                %s\n"
        "Інші помилки:                    %s\n"
        "Score: мінімум=%.1f | середній=%.1f | максимум=%.1f\n"
        "Надіслано сигналів:              %s\n"
        "=========================================",
        len(pairs),
        insufficient_data,
        generated,
        rejected_score,
        rejected_trend,
        rejected_rr,
        rejected_cooldown,
        rejected_policy,
        rejected_invalid,
        rejected_telegram,
        error_count,
        min_seen,
        avg_score,
        max_seen,
        alert_count,
    )

    return alert_count
