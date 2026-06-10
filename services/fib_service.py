import os
from typing import Any

import yfinance as yf

FIB_RATIOS = (0.236, 0.382, 0.5, 0.618, 0.786)


class FibService:
    def __init__(self, period: str | None = None):
        self.period = period or os.environ.get("FIB_LOOKBACK_PERIOD", "90d")

    def get_levels(self, symbol: str) -> dict[str, Any] | None:
        symbol = symbol.upper()
        try:
            # Ticker.history returns flat columns; yf.download uses MultiIndex for one symbol.
            data = yf.Ticker(symbol).history(period=self.period, auto_adjust=True)
            if data.empty:
                return None

            swing_high = float(data["High"].max())
            swing_low = float(data["Low"].min())
            if swing_high <= swing_low:
                return None

            span = swing_high - swing_low
            levels = []
            for ratio in FIB_RATIOS:
                price = round(swing_high - span * ratio, 2)
                levels.append(
                    {
                        "label": f"{ratio * 100:.1f}%",
                        "ratio": ratio,
                        "price": price,
                    }
                )

            return {
                "symbol": symbol,
                "period": self.period,
                "swingHigh": round(swing_high, 2),
                "swingLow": round(swing_low, 2),
                "levels": levels,
            }
        except Exception:
            return None

    def closest_level(self, symbol: str, price: float) -> dict[str, Any] | None:
        fib = self.get_levels(symbol)
        if not fib or price is None:
            return None

        closest = None
        closest_distance = None
        for level in fib["levels"]:
            distance_pct = abs(price - level["price"]) / price * 100
            if closest_distance is None or distance_pct < closest_distance:
                closest = level
                closest_distance = distance_pct

        if closest is None:
            return None

        return {
            "fib": fib,
            "level": closest,
            "distancePct": round(closest_distance, 2),
        }

    def nearest_level(self, symbol: str, price: float, proximity_pct: float) -> dict[str, Any] | None:
        closest = self.closest_level(symbol, price)
        if closest is None or closest["distancePct"] > proximity_pct:
            return None
        return closest
