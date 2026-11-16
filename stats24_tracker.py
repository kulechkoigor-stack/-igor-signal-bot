
import json
import logging
import os
import tempfile
import time

FILE = "stats24.json"
WINDOW = 24 * 60 * 60


def _load():
    if not os.path.exists(FILE):
        return {"signals": []}

    try:
        with open(FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        if not isinstance(data, dict):
            return {"signals": []}

        if not isinstance(data.get("signals"), list):
            data["signals"] = []

        return data

    except (OSError, json.JSONDecodeError):
        logging.exception("Не вдалося прочитати %s", FILE)
        return {"signals": []}


def _save(data):
    directory = os.path.dirname(os.path.abspath(FILE))
    temp_path = None

    try:
        fd, temp_path = tempfile.mkstemp(
            prefix="stats24_",
            suffix=".tmp",
            dir=directory,
        )

        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        os.replace(temp_path, FILE)
        temp_path = None

    except OSError:
        logging.exception("Не вдалося зберегти %s", FILE)

    finally:
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass


def _normalize_pump_dump(signal):
    value = signal.get("pump_dump", signal.get("type", ""))

    if isinstance(value, dict):
        value = value.get("type", value.get("label", ""))

    return str(value or "").upper()


def _get_trade_id(signal):
    value = signal.get("trade_id")
    return str(value) if value else None


def _prune(data):
    cutoff = time.time() - WINDOW
    valid = []

    for item in data["signals"]:
        if not isinstance(item, dict):
            continue

        try:
            timestamp = float(item.get("timestamp", 0) or 0)
        except (TypeError, ValueError):
            continue

        if timestamp >= cutoff:
            valid.append(item)

    data["signals"] = valid


def record_signal(signal):
    data = _load()
    _prune(data)

    trade_id = _get_trade_id(signal)

    if not trade_id:
        logging.error("stats24_tracker: сигнал не має trade_id")
        return

    if any(
        item.get("trade_id") == trade_id
        for item in data["signals"]
    ):
        logging.warning("Сигнал %s уже є в stats24", trade_id)
        return

    try:
        score = float(signal.get("score", 0) or 0)
    except (TypeError, ValueError):
        score = 0.0

    direction = str(
        signal.get("direction", signal.get("side", ""))
    ).upper()

    pump_dump = _normalize_pump_dump(signal)

    data["signals"].append({
        "trade_id": trade_id,
        "timestamp": time.time(),
        "symbol": str(signal.get("symbol", "")).upper(),
        "side": direction,
        "score": score,
        "rr": signal.get("rr", 0),
        "type": pump_dump,
        "pump_dump": pump_dump,
        "outcome": "ACTIVE",
        "tp1_hit": False,
        "tp2_hit": False,
        "tp3_hit": False,
    })

    _save(data)


def record_outcome(trade, event):
    data = _load()
    _prune(data)

    trade_id = _get_trade_id(trade)

    if not trade_id:
        logging.error("stats24_tracker: угода не має trade_id")
        return

    item = next(
        (
            entry for entry in data["signals"]
            if entry.get("trade_id") == trade_id
        ),
        None,
    )

    if item is None:
        logging.warning(
            "Не знайдено %s у статистиці за 24 години",
            trade_id,
        )
        _save(data)
        return

    event = str(event).upper()
    current = item.get("outcome", "ACTIVE")

    if current in ("TP3", "SL", "TIMEOUT"):
        return

    if event in ("TP1", "TP2", "TP3"):
        level = int(event[-1])

        # Позначаємо досягнутими всі нижчі цілі.
        for n in range(1, level + 1):
            item[f"tp{n}_hit"] = True

        item["outcome"] = event

    elif event in ("SL", "TIMEOUT"):
        item["outcome"] = event

    else:
        logging.warning(
            "Невідомий результат для stats24: %s",
            event,
        )
        return

    item["updated_at"] = time.time()
    _save(data)


def get_stats():
    data = _load()
    _prune(data)
    _save(data)
    return data


def format_stats():
    data = get_stats()
    signals = data["signals"]

    total = len(signals)
    tp1 = sum(bool(s.get("tp1_hit")) for s in signals)
    tp2 = sum(bool(s.get("tp2_hit")) for s in signals)
    tp3 = sum(bool(s.get("tp3_hit")) for s in signals)
    sl = sum(s.get("outcome") == "SL" for s in signals)
    timeout = sum(s.get("outcome") == "TIMEOUT" for s in signals)

    active = sum(
        s.get("outcome") not in ("TP3", "SL", "TIMEOUT")
        for s in signals
    )

    longs = sum(s.get("side") == "LONG" for s in signals)
    shorts = sum(s.get("side") == "SHORT" for s in signals)

    scores = []
    for s in signals:
        try:
            scores.append(float(s.get("score", 0) or 0))
        except (TypeError, ValueError):
            continue

    avg_score = sum(scores) / len(scores) if scores else 0

    pump = sum(
        "PUMP" in str(s.get("pump_dump", s.get("type", ""))).upper()
        for s in signals
    )
    dump = sum(
        "DUMP" in str(s.get("pump_dump", s.get("type", ""))).upper()
        for s in signals
    )

    return (
        "📊 СТАТИСТИКА ЗА ОСТАННІ 24 ГОДИНИ\n\n"
        f"Усього сигналів: {total}\n"
        f"TP1: {tp1} | TP2: {tp2} | TP3: {tp3}\n"
        f"SL: {sl} | Тайм-аут: {timeout}\n"
        f"Ще не завершено: {active}\n"
        f"LONG: {longs} | SHORT: {shorts}\n"
        f"PUMP: {pump} | DUMP: {dump}\n"
        f"Середній score: {avg_score:.1f}"
    )
