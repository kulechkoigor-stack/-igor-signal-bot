import argparse
import time
import logging
import sys
from datetime import datetime, timezone

# ── CLI args ──────────────────────────────────────────────────────────────────
_parser = argparse.ArgumentParser(description="Binance Futures Signal Bot")
_parser.add_argument(
    "--verbose", "-v",
    action="store_true",
    help="Enable DEBUG logging (shows per-candidate score breakdowns)",
)
_parser.add_argument(
    "--once",
    action="store_true",
    help="Run one scan and exit without the startup Telegram notice",
)
_args = _parser.parse_args()

# Configure logging before any local imports
logging.basicConfig(
    level=logging.DEBUG if _args.verbose else logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)

logger = logging.getLogger("main")

from config import (
    BINANCE_API_KEY, BINANCE_API_SECRET,
    TELEGRAM_BOT_TOKEN, SCAN_INTERVAL, MIN_SCORE,
)
from binance_client import BinanceClient
from scanner import run_scan
from telegram_notifier import send_startup_message, send_error_alert, send_daily_report
import trade_tracker

# How often (seconds) to check open trade outcomes between scans
_TRADE_POLL_INTERVAL = 60


def check_config() -> bool:
    """Validate required secrets are present."""
    missing = []
    if not BINANCE_API_KEY:
        missing.append("BINANCE_API_KEY")
    if not BINANCE_API_SECRET:
        missing.append("BINANCE_API_SECRET")
    if not TELEGRAM_BOT_TOKEN:
        missing.append("TELEGRAM_BOT_TOKEN")
    if missing:
        logger.error("Missing required secrets: %s", ", ".join(missing))
        logger.error("Set them via Replit Secrets and restart the bot.")
        return False
    return True


def main() -> None:
    logger.info("=" * 55)
    logger.info("  Binance Futures Signal Bot — starting up (Protected Mode)")
    logger.info("  Min score threshold : %s/100", MIN_SCORE)
    logger.info("  Scan interval       : %ss", SCAN_INTERVAL)
    logger.info("=" * 55)

    if not check_config():
        sys.exit(1)

    try:
        client = BinanceClient()
    except Exception as exc:
        logger.exception("Failed to initialize Binance client: %s", exc)
        sys.exit(1)

    if not _args.once:
        try:
            send_startup_message()
        except Exception as exc:
            logger.exception("Startup Telegram message error: %s", exc)

    consecutive_errors = 0
    _last_report_day = datetime.now(timezone.utc).date()

    while True:
        try:
            t_start = time.time()
            logger.info("SCAN STARTED — починаю сканування ринку")

            try:
                alerts = run_scan(client)
                logger.info("SCAN FINISHED — надіслано сигналів: %s", alerts)
            except Exception as scan_err:
                consecutive_errors += 1
                logger.exception(
                    "SCAN FAILED — помилка під час сканування (помилка №%s): %s",
                    consecutive_errors, scan_err,
                )
                try:
                    if consecutive_errors == 3:
                        send_error_alert(str(scan_err)[:200])
                except Exception:
                    logger.exception("Could not send Telegram error alert")

                if _args.once:
                    sys.exit(1)

            if _args.once:
                logger.info("One-shot scan complete; exiting.")
                break

            # Reset consecutive errors only after a successful scan.
            else:
                # A successful scan sets alerts above and reaches this point
                # without an exception. Reset only if the scan completed.
                if 'alerts' in locals():
                    consecutive_errors = 0

            elapsed = time.time() - t_start
            sleep_time = max(0, SCAN_INTERVAL - elapsed)
            logger.info(
                "Next scan in %.0fs (scan took %.0fs) | open trades being tracked: %s",
                sleep_time, elapsed, trade_tracker.open_count(),
            )

            _deadline = time.time() + sleep_time
            while time.time() < _deadline:
                _today = datetime.now(timezone.utc).date()
                if _today > _last_report_day:
                    logger.info("UTC midnight passed — sending daily report")
                    try:
                        send_daily_report()
                    except Exception:
                        logger.exception("Daily report error")
                    _last_report_day = _today

                try:
                    trade_tracker.poll(client)
                except Exception:
                    logger.exception("Trade tracker poll error")

                _nap = min(_TRADE_POLL_INTERVAL, _deadline - time.time())
                if _nap > 0:
                    time.sleep(_nap)

        except KeyboardInterrupt:
            logger.info("Bot stopped by user.")
            break
        except Exception as exc:
            consecutive_errors += 1
            logger.exception("Main loop critical error #%s: %s", consecutive_errors, exc)
            try:
                if consecutive_errors == 3:
                    send_error_alert(str(exc)[:200])
            except Exception:
                logger.exception("Could not send Telegram error alert")
            backoff = min(300, 60 * consecutive_errors)
            logger.info("Backing off %ss before retry and keeping bot alive…", backoff)
            time.sleep(backoff)


if __name__ == "__main__":
    main()
