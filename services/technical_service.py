import json
import re
from typing import Any

import pandas as pd
import yfinance as yf

from db.database import get_connection

BLOCK_HEADER = re.compile(
    r"\[TECHNICAL ANALYSIS EXPORT:\s*([A-Z][A-Z0-9.\-]+)\s*\]",
    re.I,
)
FIB_LEVEL_STYLES = (
    (("0% (High)", "0% High", "0%"), "high", "0% High", "#a78bfa"),
    (("38.2% Retracement", "38.2% Fib"), "fib-0.382", "38.2% Fib", "#3b82f6"),
    (("50.0% Center Line", "50.0% Center"), "fib-0.5", "50.0% Center", "#f59e0b"),
    (("61.8% Golden Pocket", "61.8% Golden"), "fib-0.618", "61.8% Golden", "#ef4444"),
    (("100% (Low Base)", "100% Low Base", "100% Base", "100%"), "base", "100% Base", "#9aa8bc"),
)
TREND_LINE = re.compile(
    r"^- (T\d+) \((Bullish|Bearish)\):\s+"
    r"(\d{4}-\d{2}-\d{2})\s+([\d.,]+)\s*\$\s+to\s+"
    r"(\d{4}-\d{2}-\d{2})\s+([\d.,]+)\s*\$"
    r"(?:\s*\(Move:\s*([\d.]+)%\))?",
    re.I,
)
PEAK_PAIR = re.compile(
    r"(?:Peak\s+)?High:?\s*([\d.,]+)\s*\$.*?(?:Peak\s+)?Low:?\s*([\d.,]+)\s*\$",
    re.I,
)
FIB_LINE = re.compile(r"^- (.+?):\s*([\d.,]+)\s*\$", re.I)
WINDOW_LINE = re.compile(
    r"Time window:\s*(\d{4}-\d{2}(?:-\d{2})?)\s*(?:→|->|to)\s*(\d{4}-\d{2}(?:-\d{2})?)",
    re.I,
)
FIB_ANCHOR_LINE = re.compile(r"Fibonacci anchor:\s*(.+)", re.I)


class TechnicalService:
    def get_snapshot(self, symbol: str) -> dict[str, Any] | None:
        symbol = symbol.upper()
        with get_connection() as conn:
            row = conn.execute(
                """
                SELECT symbol, window_start, window_end, fib_anchor,
                       trends_json, fib_levels_json, updated_at
                FROM symbol_technical
                WHERE symbol = ?
                """,
                (symbol,),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_snapshot(row)

    def upsert_snapshot(self, symbol: str, snapshot: dict[str, Any]) -> dict[str, Any]:
        symbol = symbol.upper()
        trends = snapshot.get("trends") or []
        fib_levels = snapshot.get("fibLevels") or {}
        with get_connection() as conn:
            conn.execute(
                """
                INSERT INTO symbol_technical (
                    symbol, window_start, window_end, fib_anchor,
                    trends_json, fib_levels_json, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
                ON CONFLICT(symbol) DO UPDATE SET
                    window_start = excluded.window_start,
                    window_end = excluded.window_end,
                    fib_anchor = excluded.fib_anchor,
                    trends_json = excluded.trends_json,
                    fib_levels_json = excluded.fib_levels_json,
                    updated_at = datetime('now')
                """,
                (
                    symbol,
                    snapshot.get("windowStart"),
                    snapshot.get("windowEnd"),
                    snapshot.get("fibAnchor"),
                    json.dumps(trends),
                    json.dumps(fib_levels),
                ),
            )
            conn.commit()
        result = self.get_snapshot(symbol)
        assert result is not None
        return result

    @staticmethod
    def _trim_export_body(body: str) -> str:
        header_match = BLOCK_HEADER.search(body)
        if header_match:
            body = body[header_match.end() :]
        trimmed = re.split(r"\n={5,}", body, maxsplit=1)[0]
        next_block = BLOCK_HEADER.search(trimmed)
        if next_block:
            trimmed = trimmed[: next_block.start()]
        return trimmed.strip()

    @staticmethod
    def parse_export_body(body: str) -> dict[str, Any] | None:
        body = TechnicalService._trim_export_body(body)
        snapshot: dict[str, Any] = {}
        window_match = WINDOW_LINE.search(body)
        if window_match:
            snapshot["windowStart"] = window_match.group(1)
            snapshot["windowEnd"] = window_match.group(2)

        anchor_match = FIB_ANCHOR_LINE.search(body)
        if anchor_match:
            snapshot["fibAnchor"] = anchor_match.group(1).strip()

        trends = TechnicalService._parse_trend_lines(body)
        if trends:
            snapshot["trends"] = trends

        fib_levels = TechnicalService._parse_fib_levels(body)
        if fib_levels:
            snapshot["fibLevels"] = fib_levels

        if not snapshot:
            return None
        return snapshot

    @staticmethod
    def _parse_trend_lines(body: str) -> list[dict[str, Any]]:
        trends: list[dict[str, Any]] = []
        for raw_line in body.splitlines():
            line = raw_line.strip()
            if not re.match(r"^- T\d+", line, re.I):
                continue
            match = TREND_LINE.match(line)
            if not match:
                continue
            label, trend_type, start_date, price_start, end_date, price_end, move_pct = match.groups()
            peak_match = PEAK_PAIR.search(line)
            peak_high = TechnicalService._clean_number(peak_match.group(1)) if peak_match else None
            peak_low = TechnicalService._clean_number(peak_match.group(2)) if peak_match else None
            direction = "up" if trend_type.lower() == "bullish" else "down"
            trends.append(
                {
                    "label": label.upper(),
                    "type": trend_type.title(),
                    "direction": direction,
                    "startDate": start_date,
                    "endDate": end_date,
                    "priceStart": TechnicalService._clean_number(price_start),
                    "priceEnd": TechnicalService._clean_number(price_end),
                    "movePct": TechnicalService._clean_number(move_pct),
                    "peakHigh": peak_high,
                    "peakLow": peak_low,
                }
            )
        return trends

    @staticmethod
    def _parse_fib_levels(body: str) -> dict[str, float]:
        levels: dict[str, float] = {}
        in_fib = False
        for raw_line in body.splitlines():
            line = raw_line.strip()
            if re.match(r"^Fibonacci Levels:\s*$", line, re.I):
                in_fib = True
                continue
            if not in_fib:
                continue
            if not line.startswith("- "):
                if line and not line.startswith("["):
                    break
                continue
            match = FIB_LINE.match(line)
            if not match:
                continue
            label = match.group(1).strip()
            value = TechnicalService._clean_number(match.group(2))
            if value is not None:
                levels[label] = value
        return levels

    def trend_waves_for_symbol(self, symbol: str, snapshot: dict[str, Any] | None) -> list[dict[str, Any]]:
        if not snapshot or not snapshot.get("trends"):
            return []
        fib_levels = snapshot.get("fibLevels") or {}
        fib_high = self._level_price(fib_levels, ("0% (High)", "0% High", "0%"))
        fib_low = self._level_price(fib_levels, ("100% (Low Base)", "100% Low Base", "100% Base", "100%"))
        waves = []
        for trend in snapshot["trends"]:
            wave = dict(trend)
            wave.update(self._leg_display_fields(wave))
            if wave.get("label") == "T1" and fib_high is not None and fib_low is not None:
                wave["peakHigh"] = fib_high
                wave["peakLow"] = fib_low
            elif wave.get("peakHigh") is None or wave.get("peakLow") is None:
                peaks = self._peaks_for_date_range(symbol, wave.get("startDate"), wave.get("endDate"))
                wave["peakHigh"] = wave.get("peakHigh") or peaks.get("peakHigh")
                wave["peakLow"] = wave.get("peakLow") or peaks.get("peakLow")
            waves.append(wave)
        return self._sort_trends_by_start_date(waves)

    @staticmethod
    def _sort_trends_by_start_date(trends: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return sorted(
            trends,
            key=lambda trend: (
                trend.get("startDate") or "",
                trend.get("label") or "",
            ),
        )

    @staticmethod
    def _leg_display_fields(trend: dict[str, Any]) -> dict[str, Any]:
        trend_type = str(trend.get("type") or "").lower()
        price_start = trend.get("priceStart")
        price_end = trend.get("priceEnd")
        start_date = trend.get("startDate") or "—"
        end_date = trend.get("endDate") or "—"
        if trend_type == "bullish":
            leg_pattern = "Low → Peak (Bullish)"
            low_price = min(price_start, price_end) if price_start is not None and price_end is not None else price_start
            high_price = max(price_start, price_end) if price_start is not None and price_end is not None else price_end
        else:
            leg_pattern = "Peak → Low (Bearish)"
            high_price = max(price_start, price_end) if price_start is not None and price_end is not None else price_start
            low_price = min(price_start, price_end) if price_start is not None and price_end is not None else price_end
        return {
            "legPattern": leg_pattern,
            "legSummary": f"From {start_date} until {end_date} · {leg_pattern}",
            "displayLow": low_price,
            "displayHigh": high_price,
        }

    @staticmethod
    def style_for_fib_label(label: str) -> dict[str, str]:
        for aliases, key, short_label, color in FIB_LEVEL_STYLES:
            if label in aliases:
                return {"key": key, "shortLabel": short_label, "color": color}

        lowered = str(label or "").lower()
        if lowered.startswith("0%") or ("0%" in lowered and "high" in lowered):
            return {"key": "high", "shortLabel": "0% High", "color": "#a78bfa"}
        if "38.2" in lowered:
            return {"key": "fib-0.382", "shortLabel": "38.2% Fib", "color": "#3b82f6"}
        if "50.0" in lowered or "center" in lowered:
            return {"key": "fib-0.5", "shortLabel": "50.0% Center", "color": "#f59e0b"}
        if "61.8" in lowered or "golden" in lowered:
            return {"key": "fib-0.618", "shortLabel": "61.8% Golden", "color": "#ef4444"}
        if lowered.startswith("100%") or ("low" in lowered and "base" in lowered):
            return {"key": "base", "shortLabel": "100% Base", "color": "#9aa8bc"}
        return {"key": "fib-other", "shortLabel": label, "color": "#9aa8bc"}

    @staticmethod
    def fib_levels_list(snapshot: dict[str, Any] | None) -> list[dict[str, Any]]:
        if not snapshot:
            return []
        levels_map = snapshot.get("fibLevels") or {}
        order = (
            "0% (High)",
            "38.2% Retracement",
            "50.0% Center Line",
            "61.8% Golden Pocket",
            "100% (Low Base)",
        )
        listed = []
        seen = set()
        for label in order:
            if label in levels_map:
                style = TechnicalService.style_for_fib_label(label)
                listed.append(
                    {
                        "label": label,
                        "price": levels_map[label],
                        "key": style["key"],
                        "shortLabel": style["shortLabel"],
                        "color": style["color"],
                    }
                )
                seen.add(label)
        for label, price in levels_map.items():
            if label not in seen:
                style = TechnicalService.style_for_fib_label(label)
                listed.append(
                    {
                        "label": label,
                        "price": price,
                        "key": style["key"],
                        "shortLabel": style["shortLabel"],
                        "color": style["color"],
                    }
                )
        return listed

    def chart_timeline(
        self,
        symbol: str,
        snapshot: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        if not snapshot:
            return None
        window_start = snapshot.get("windowStart")
        window_end = snapshot.get("windowEnd")
        if not window_start or not window_end:
            return None

        start = window_start if len(window_start) > 7 else f"{window_start}-01"
        end = window_end if len(window_end) > 7 else f"{window_end}-01"
        try:
            end_exclusive = pd.to_datetime(end) + pd.offsets.MonthEnd(0) + pd.Timedelta(days=1)
            history = yf.Ticker(symbol.upper()).history(
                start=start,
                end=end_exclusive.strftime("%Y-%m-%d"),
                auto_adjust=True,
            )
            if history.empty:
                return None
            points = [
                {
                    "date": index.strftime("%Y-%m-%d"),
                    "price": round(float(row["Close"]), 2),
                }
                for index, row in history.iterrows()
            ]
            return {
                "windowStart": window_start,
                "windowEnd": window_end,
                "startDate": points[0]["date"],
                "endDate": points[-1]["date"],
                "points": points,
            }
        except Exception:
            return None

    def fib_from_snapshot(self, symbol: str, snapshot: dict[str, Any] | None) -> dict[str, Any] | None:
        if not snapshot or not snapshot.get("fibLevels"):
            return None
        levels_map = snapshot["fibLevels"]
        high = self._level_price(levels_map, ("0% (High)", "0% High", "0%"))
        low = self._level_price(levels_map, ("100% (Low Base)", "100% Low Base", "100% Base", "100%"))
        if high is None or low is None:
            return None

        ratio_labels = {
            0.382: ("38.2% Retracement", "38.2% Fib"),
            0.5: ("50.0% Center Line", "50.0% Center"),
            0.618: ("61.8% Golden Pocket", "61.8% Golden"),
        }
        levels = []
        for ratio, labels in ratio_labels.items():
            price = self._level_price(levels_map, labels)
            if price is None:
                continue
            levels.append({"label": f"{ratio * 100:.1f}%", "ratio": ratio, "price": price})

        window = None
        if snapshot.get("windowStart") and snapshot.get("windowEnd"):
            window = f"{snapshot['windowStart']} → {snapshot['windowEnd']}"

        return {
            "symbol": symbol.upper(),
            "period": window,
            "swingHigh": high,
            "swingLow": low,
            "levels": levels,
            "anchorNote": snapshot.get("fibAnchor"),
            "anchorTrend": self._anchor_trend_label(snapshot),
        }

    @staticmethod
    def _anchor_trend_label(snapshot: dict[str, Any]) -> str | None:
        anchor = str(snapshot.get("fibAnchor") or "").strip()
        if anchor and not anchor.lower().startswith("window high/low"):
            return anchor
        trends = snapshot.get("trends") or []
        if not trends:
            return anchor or None
        main = trends[0]
        return (
            f"{main.get('label', 'T1')} ({main.get('type', 'Trend')}): "
            f"{main.get('startDate', '—')} → {main.get('endDate', '—')}"
        )

    @staticmethod
    def _level_price(levels_map: dict[str, float], labels: tuple[str, ...]) -> float | None:
        for label in labels:
            if label in levels_map:
                return round(float(levels_map[label]), 2)
        for key, value in levels_map.items():
            if any(token in key for token in labels):
                return round(float(value), 2)
        return None

    @staticmethod
    def _peaks_for_date_range(
        symbol: str,
        start_date: str | None,
        end_date: str | None,
    ) -> dict[str, float | None]:
        if not start_date or not end_date:
            return {"peakHigh": None, "peakLow": None}
        try:
            import pandas as pd

            end_exclusive = pd.to_datetime(end_date) + pd.Timedelta(days=1)
            history = yf.Ticker(symbol.upper()).history(
                start=start_date,
                end=end_exclusive.strftime("%Y-%m-%d"),
                auto_adjust=True,
            )
            if history.empty:
                return {"peakHigh": None, "peakLow": None}
            return {
                "peakHigh": round(float(history["High"].max()), 2),
                "peakLow": round(float(history["Low"].min()), 2),
            }
        except Exception:
            return {"peakHigh": None, "peakLow": None}

    @staticmethod
    def _clean_number(value: str | None) -> float | None:
        if value is None:
            return None
        text = str(value).strip().replace(",", "")
        if not text:
            return None
        try:
            return round(float(text), 2)
        except ValueError:
            return None

    @staticmethod
    def _row_to_snapshot(row) -> dict[str, Any]:
        trends = json.loads(row["trends_json"] or "[]")
        fib_levels = json.loads(row["fib_levels_json"] or "{}")
        return {
            "symbol": row["symbol"],
            "windowStart": row["window_start"],
            "windowEnd": row["window_end"],
            "fibAnchor": row["fib_anchor"],
            "trends": trends,
            "fibLevels": fib_levels,
            "updatedAt": row["updated_at"],
        }
