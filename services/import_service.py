import json
import re
from typing import Any

from services.holdings_service import HoldingsService
from services.portfolio_service import PortfolioService

SYMBOL_LINE = re.compile(
    r"^\s*(?:#{1,3}\s*|[\*\-]\s*)?(?:={2,}\s*)?"
    r"([A-Z][A-Z0-9.\-]{0,9})(?:\s*={2,})?\s*$"
)
KV_LINE = re.compile(r"^\s*([A-Za-z][A-Za-z0-9 _\-/]*?)\s*[:=\|]\s*(.+?)\s*$")

FIELD_ALIASES = {
    "currentprice": "currentPrice",
    "current price": "currentPrice",
    "current": "currentPrice",
    "price": "currentPrice",
    "last": "currentPrice",
    "last price": "currentPrice",
    "targetprice": "targetPrice",
    "target price": "targetPrice",
    "target": "targetPrice",
    "1y target": "targetPrice",
    "buybelow": "buyBelow",
    "buy below": "buyBelow",
    "buy-below": "buyBelow",
    "sellabove": "sellAbove",
    "sell above": "sellAbove",
    "sell-above": "sellAbove",
    "quantity": "quantity",
    "shares": "quantity",
    "qty": "quantity",
    "costbasis": "costBasis",
    "cost basis": "costBasis",
    "cost": "costBasis",
    "avgcost": "costBasis",
    "average cost": "costBasis",
}


class ImportService:
    def __init__(self):
        self.portfolio_service = PortfolioService()
        self.holdings_service = HoldingsService()

    def import_payload(self, payload: Any) -> dict[str, Any]:
        if isinstance(payload, str):
            payload = json.loads(payload)

        if not isinstance(payload, dict):
            raise ValueError("Import payload must be a JSON object.")

        symbols_imported = 0
        holdings_imported = 0

        if "symbols" in payload and isinstance(payload["symbols"], list):
            for item in payload["symbols"]:
                if not isinstance(item, dict) or not item.get("symbol"):
                    continue
                symbol = item["symbol"]
                self.portfolio_service.upsert_symbol(symbol, item)
                symbols_imported += 1
                if any(key in item for key in ("quantity", "shares", "costBasis", "cost_basis")):
                    self.holdings_service.upsert_holding(symbol, item)
                    holdings_imported += 1

        if "holdings" in payload and isinstance(payload["holdings"], list):
            for item in payload["holdings"]:
                if not isinstance(item, dict) or not item.get("symbol"):
                    continue
                symbol = item["symbol"]
                self.portfolio_service.upsert_symbol(symbol, item)
                self.holdings_service.upsert_holding(symbol, item)
                symbols_imported += 1
                holdings_imported += 1

        for symbol, details in payload.items():
            if symbol in ("symbols", "holdings", "portfolio", "metadata"):
                continue
            if not isinstance(details, dict):
                continue
            self.portfolio_service.upsert_symbol(symbol, details)
            symbols_imported += 1
            if any(key in details for key in ("quantity", "shares", "costBasis", "cost_basis")):
                self.holdings_service.upsert_holding(symbol, details)
                holdings_imported += 1

        return {
            "symbolsImported": symbols_imported,
            "holdingsImported": holdings_imported,
            "symbols": self.portfolio_service.list_symbols(),
            "holdings": self.holdings_service.list_holdings(),
        }

    def import_file(self, filename: str, raw_bytes: bytes) -> dict[str, Any]:
        text = raw_bytes.decode("utf-8-sig")
        lower_name = filename.lower()

        if lower_name.endswith(".json"):
            return self._with_format(self.import_payload(json.loads(text)), "json")

        if lower_name.endswith(".csv"):
            return self._with_format(self.import_csv(text), "csv")

        if lower_name.endswith(".txt"):
            return self._with_format(self.import_txt(text), "txt")

        try:
            return self._with_format(self.import_payload(json.loads(text)), "json")
        except json.JSONDecodeError:
            return self._with_format(self.import_txt(text), "txt")

    def import_txt(self, text: str) -> dict[str, Any]:
        stripped = text.strip()
        if not stripped:
            raise ValueError("Text file is empty.")

        try:
            return self.import_payload(json.loads(stripped))
        except json.JSONDecodeError:
            pass

        if self._looks_like_csv(stripped):
            return self.import_csv(stripped)

        records = self._parse_txt_blocks(stripped)
        if not records:
            raise ValueError(
                "Could not parse text file. Use symbol blocks with key: value lines, "
                "or save your export as JSON/CSV."
            )

        return self.import_payload(records)

    def import_csv(self, text: str) -> dict[str, Any]:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if len(lines) < 2:
            raise ValueError("CSV must include a header row and at least one data row.")

        delimiter = "\t" if "\t" in lines[0] and "," not in lines[0] else ","
        headers = [part.strip().lower() for part in lines[0].split(delimiter)]
        symbol_idx = self._header_index(headers, ("symbol", "ticker"))
        if symbol_idx is None:
            raise ValueError("CSV must include a symbol or ticker column.")

        imported = {"symbolsImported": 0, "holdingsImported": 0}
        for line in lines[1:]:
            values = [part.strip() for part in line.split(delimiter)]
            row = {headers[i]: values[i] for i in range(min(len(headers), len(values)))}
            symbol = row.get(headers[symbol_idx])
            if not symbol:
                continue
            payload = {
                "symbol": symbol.upper(),
                "currentPrice": row.get("currentprice") or row.get("price"),
                "targetPrice": row.get("targetprice") or row.get("target"),
                "buyBelow": row.get("buybelow"),
                "sellAbove": row.get("sellabove"),
                "quantity": row.get("quantity") or row.get("shares"),
                "costBasis": row.get("costbasis") or row.get("cost"),
            }
            result = self.import_payload({symbol.upper(): payload})
            imported["symbolsImported"] += result["symbolsImported"]
            imported["holdingsImported"] += result["holdingsImported"]

        return {
            **imported,
            "symbols": self.portfolio_service.list_symbols(),
            "holdings": self.holdings_service.list_holdings(),
        }

    def _parse_txt_blocks(self, text: str) -> dict[str, dict[str, Any]]:
        records: dict[str, dict[str, Any]] = {}
        current_symbol: str | None = None

        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line:
                continue

            symbol_match = SYMBOL_LINE.match(line)
            if symbol_match and not KV_LINE.match(line):
                current_symbol = symbol_match.group(1).upper()
                records.setdefault(current_symbol, {})
                continue

            kv_match = KV_LINE.match(line)
            if not kv_match:
                continue

            field_key = self._normalize_field_name(kv_match.group(1))
            mapped = FIELD_ALIASES.get(field_key)
            if not mapped:
                continue

            value = self._clean_number(kv_match.group(2))
            if value is None:
                continue

            if current_symbol is None:
                continue

            records.setdefault(current_symbol, {})[mapped] = value

        return {symbol: details for symbol, details in records.items() if details}

    def _looks_like_csv(self, text: str) -> bool:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if len(lines) < 2:
            return False
        first = lines[0].lower()
        return "symbol" in first or "ticker" in first

    def _normalize_field_name(self, name: str) -> str:
        return re.sub(r"\s+", " ", name.strip().lower())

    def _clean_number(self, value: str) -> float | None:
        if value is None:
            return None
        cleaned = re.sub(r"[^\d.\-]", "", value.replace(",", ""))
        if not cleaned or cleaned in ("-", "."):
            return None
        try:
            return float(cleaned)
        except ValueError:
            return None

    def _header_index(self, headers: list[str], names: tuple[str, ...]) -> int | None:
        for name in names:
            if name in headers:
                return headers.index(name)
        return None

    def _with_format(self, result: dict[str, Any], fmt: str) -> dict[str, Any]:
        return {**result, "format": fmt}
