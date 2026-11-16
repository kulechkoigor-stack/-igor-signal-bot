
"""
OKX USDT Perpetual (Linear Swap) public REST client.

Uses public OKX API endpoints; API keys are not required.
OKX base URL: https://www.okx.com/api/v5
"""

import logging
import requests
import pandas as pd

from config import TIMEFRAME

logger = logging.getLogger(__name__)

_BASE = "https://www.okx.com/api/v5"

_TF_MAP = {
    "1m": "1m",
    "3m": "3m",
    "5m": "5m",
    "15m": "15m",
    "30m": "30m",
    "1h": "1H",
    "2h": "2H",
    "4h": "4H",
    "6h": "6H",
    "12h": "12H",
    "1d": "1D",
    "3d": "3D",
    "1w": "1W",
}


def _to_okx_bar(tf: str) -> str:
    return _TF_MAP.get(tf.lower(), tf)


class BinanceClient:
    """
    Kept as BinanceClient for compatibility with existing imports.
    Uses the public OKX API.
    """

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(
            {"User-Agent": "FuturesSignalBot/1.0"}
        )
        self._prev_oi: dict[str, float] = {}
        self._pair_rotation = 0

    def _get(self, path: str, params: dict | None = None) -> dict:
        response = self.session.get(
            f"{_BASE}{path}",
            params=params,
            timeout=20,
        )
        response.raise_for_status()
        result = response.json()

        if result.get("code") not in (None, "0"):
            raise RuntimeError(
                f"OKX API error {result.get('code')}: "
                f"{result.get('msg', 'unknown error')}"
            )

        return result

    def get_top_pairs(self, n: int = 100) -> list[str]:
        """Return top USDT perpetual swaps by 24h quote volume."""
        try:
            result = self._get(
                "/market/tickers",
                params={"instType": "SWAP"},
            )
            tickers = result.get("data", [])

            usdt_perps = [
                ticker
                for ticker in tickers
                if ticker.get("instId", "").endswith("-USDT-SWAP")
            ]

            ranked = sorted(
                usdt_perps,
                key=lambda ticker: float(
                    ticker.get("volCcy24h") or 0
                ),
                reverse=True,
            )

            top = [ticker["instId"] for ticker in ranked[:n]]

            if top:
                shift = max(1, len(top) // 5)
                self._pair_rotation = (
                    self._pair_rotation + shift
                ) % len(top)
                top = (
                    top[self._pair_rotation:]
                    + top[:self._pair_rotation]
                )

            logger.info(
                "Fetched %s OKX USDT perpetual pairs",
                len(top),
            )
            return top

        except Exception as exc:
            logger.error("get_top_pairs error: %s", exc)
            return []

    def get_top_gainers(self, limit: int = 15) -> list[str]:
        """Return USDT perpetual swaps with the highest 24h price gain."""
        try:
            result = self._get(
                "/market/tickers",
                params={"instType": "SWAP"},
            )

            gainers = []

            for ticker in result.get("data", []):
                symbol = ticker.get("instId", "")

                if not symbol.endswith("-USDT-SWAP"):
                    continue

                try:
                    last_price = float(ticker.get("last") or 0)
                    open_price = float(
                        ticker.get("open24h")
                        or ticker.get("sodUtc8")
                        or 0
                    )

                    if last_price > 0 and open_price > 0:
                        change_pct = (
                            (last_price - open_price) / open_price
                        ) * 100
                        gainers.append((symbol, change_pct))

                except (ValueError, TypeError):
                    continue

            gainers.sort(key=lambda item: item[1], reverse=True)
            result_symbols = [
                item[0] for item in gainers[:limit]
            ]

            logger.info(
                "Fetched %s OKX gainers",
                len(result_symbols),
            )
            return result_symbols

        except Exception as exc:
            logger.error("get_top_gainers error: %s", exc)
            return []

    def get_ohlcv(
        self,
        symbol: str,
        timeframe: str = TIMEFRAME,
        limit: int = 300,
    ) -> pd.DataFrame | None:
        """
        Fetch candles from OKX.
        Returns chronological OHLCV data indexed by UTC timestamp.
        Only confirmed (closed) candles are returned.
        """
        try:
            bar = _to_okx_bar(timeframe)

            result = self._get(
                "/market/candles",
                params={
                    "instId": symbol,
                    "bar": bar,
                    "limit": min(limit, 300),
                },
            )

            rows = result.get("data", [])
            if not rows:
                return None

            df = pd.DataFrame(
                rows,
                columns=[
                    "ts",
                    "open",
                    "high",
                    "low",
                    "close",
                    "volume",
                    "vol_ccy",
                    "vol_ccy_quote",
                    "confirm",
                ],
            )

            # OKX confirm="1" means the candle is closed.
            # Remove the currently forming candle.
            df = df[df["confirm"].astype(str) == "1"].copy()

            if df.empty:
                logger.warning(
                    "No confirmed candles returned for %s",
                    symbol,
                )
                return None

            df = df[
                ["ts", "open", "high", "low", "close", "volume"]
            ].copy()

            df["ts"] = pd.to_datetime(
                df["ts"].astype("int64"),
                unit="ms",
                utc=True,
            )
            df.set_index("ts", inplace=True)
            df = df.astype(float)
            df.sort_index(inplace=True)

            return df

        except Exception as exc:
            logger.warning("get_ohlcv(%s) error: %s", symbol, exc)
            return None

    def get_price(self, symbol: str) -> float | None:
        """Fetch the latest traded price."""
        try:
            result = self._get(
                "/market/ticker",
                params={"instId": symbol},
            )
            items = result.get("data", [])

            if items:
                return float(items[0]["last"])

        except (ValueError, TypeError, KeyError, requests.RequestException) as exc:
            logger.warning("get_price(%s) error: %s", symbol, exc)
        except Exception as exc:
            logger.warning("get_price(%s) error: %s", symbol, exc)

        return None

    def get_trade_flow(
        self,
        symbol: str,
        limit: int = 100,
    ) -> dict:
        """
        Estimate recent aggressive buy/sell volume from OKX public trades.

        Positive imbalance means more buy-side volume.
        Negative imbalance means more sell-side volume.
        This is diagnostic only, not a guaranteed price prediction.
        """
        result = {
            "buy_volume": 0.0,
            "sell_volume": 0.0,
            "imbalance_pct": 0.0,
            "trades": 0,
            "available": False,
        }

        try:
            result_data = self._get(
                "/market/trades",
                params={
                    "instId": symbol,
                    "limit": max(1, min(int(limit), 500)),
                },
            )

            trades = result_data.get("data", [])
            if not trades:
                return result

            buy_volume = 0.0
            sell_volume = 0.0
            valid_trades = 0

            for trade in trades:
                try:
                    side = trade.get("side", "").lower()
                    size = float(trade.get("sz") or 0)

                    if size <= 0:
                        continue

                    if side == "buy":
                        buy_volume += size
                        valid_trades += 1
                    elif side == "sell":
                        sell_volume += size
                        valid_trades += 1

                except (ValueError, TypeError):
                    continue

            total_volume = buy_volume + sell_volume

            if total_volume <= 0:
                return result

            imbalance = (
                (buy_volume - sell_volume) / total_volume
            ) * 100

            result.update({
                "buy_volume": round(buy_volume, 8),
                "sell_volume": round(sell_volume, 8),
                "imbalance_pct": round(imbalance, 2),
                "trades": valid_trades,
                "available": True,
            })

            return result

        except Exception as exc:
            logger.debug(
                "get_trade_flow(%s) error: %s",
                symbol,
                exc,
            )
            return result

    def get_open_interest(self, symbol: str) -> float:
        """Fetch current open interest from the public OKX endpoint."""
        try:
            result = self._get(
                "/public/open-interest",
                params={
                    "instType": "SWAP",
                    "instId": symbol,
                },
            )

            items = result.get("data", [])
            if items:
                return float(items[0].get("oi") or 0)

        except Exception as exc:
            logger.warning(
                "get_open_interest(%s) error: %s",
                symbol,
                exc,
            )

        return 0.0

    def get_oi_change_pct(self, symbol: str) -> float:
        """
        Calculate OI percentage change since the previous poll.
        The first successful poll establishes a baseline and returns 0.
        """
        current_oi = self.get_open_interest(symbol)

        if current_oi <= 0:
            return 0.0

        previous_oi = self._prev_oi.get(symbol, current_oi)
        self._prev_oi[symbol] = current_oi

        if previous_oi <= 0:
            return 0.0

        change_pct = (
            (current_oi - previous_oi) / previous_oi
        ) * 100

        return round(change_pct, 2)
