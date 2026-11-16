import time
import logging
from binance_client import BinanceClient
from scanner import run_scan
import trade_tracker

# Налаштування логування
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)


def main():
    logger.info("========== ЗАПУСК ТОРГОВОГО БОТА ==========")
    
    try:
        client = BinanceClient()
    except Exception as exc:
        logger.error("Не вдалося ініціалізувати BinanceClient: %s", exc, exc_info=True)
        return

    logger.info("Бот успішно підключено. Починаємо роботу циклу сканування та трекінгу.")

    while True:
        try:
            # 1. Скануємо ринок і шукаємо нові сигнали на входження
            run_scan(client)

        except Exception as exc:
            logger.error("Помилка під час сканування ринку: %s", exc, exc_info=True)

        try:
            # 2. ПЕРЕВІРЯЮЧИЙ ТРЕКЕР: Оновлює ціни відкритих позицій 
            # та відправляє TP/SL у Telegram, якщо вони спрацювали
            trade_tracker.poll(client)

        except Exception as exc:
            logger.error("Помилка у трекері угод (trade_tracker.poll): %s", exc, exc_info=True)

        # Пауза між ітераціями основного циклу (можеш змінити за потреби, наприклад, на 15-30 секунд)
        time.sleep(20)


if __name__ == "__main__":
    main()
