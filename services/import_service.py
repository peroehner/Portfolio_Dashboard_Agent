import ast
import json
import re
from typing import Any

from services.holdings_service import HoldingsService
from services.portfolio_service import PortfolioService

SYMBOL_LINE = re.compile(
    r"^\s*(?:#{1,3}\s*|[\*\-]\s*)?(?:={2,}\s*)?"
    r"([A-Z][A-Z0-9.\-]{0,9})(?:\s*={2,})?\s*(?:[-–—].*)?$"
)
SYMBOL_KV = re.compile(
    r"^\s*(?:symbol|ticker|stock)\s*[:=\|]\s*([A-Z][A-Z0-9.\-]{0,9})\s*$",
    re.I,
)
KV_LINE = re.compile(r"^\s*([A-Za-z][A-Za-z0-9 _\-/]*?)\s*[:=\|]\s*(.+?)\s*$")
CAMEL_FIELD = re.compile(
    r"^(currentPrice|targetPrice|buyBelow|sellAbove|costBasis|quantity|shares)$"
)
POSITIONAL_LINE = re.compile(
    r"^\s*([A-Z][A-Z0-9.\-]{0,9})\s*[,;\t|]\s*"
    r"([\d.,$€£+\-]+)\s*[,;\t|]?\s*([\d.,$€£+\-]*)\s*[,;\t|]?\s*([\d.,$€£+\-]*)\s*[,;\t|]?\s*([\d.,$€£+\-]*)\s*$"
)

FIELD_ALIASES = {
    "currentprice": "currentPrice",
    "current price": "currentPrice",
    "current": "currentPrice",
    "price": "currentPrice",
    "last": "currentPrice",
    "last price": "currentPrice",
    "market price": "currentPrice",
    "targetprice": "targetPrice",
    "target price": "targetPrice",
    "target": "targetPrice",
    "1y target": "targetPrice",
    "1y price target": "targetPrice",
    "price target": "targetPrice",
    "buybelow": "buyBelow",
    "buy below": "buyBelow",
    "buy-below": "buyBelow",
    "buy": "buyBelow",
    "sellabove": "sellAbove",
    "sell above": "sellAbove",
    "sell-above": "sellAbove",
    "sell": "sellAbove",
    "quantity": "quantity",
    "shares": "quantity",
    "qty": "quantity",
    "position": "quantity",
    "costbasis": "costBasis",
    "cost basis": "costBasis",
    "cost": "costBasis",
    "avgcost": "costBasis",
    "average cost": "costBasis",
    "avg cost": "costBasis",
}


class ImportService:
    def __init__(self):
        self.portfolio_service = PortfolioService()
        self.holdings_service = HoldingsService()

    def import_payload(self, payload: Any) -> dict[str, Any]:
        if isinstance(payload, str):
            payload = self._parse_structured_text(payload)

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
            normalized = self._normalize_symbol_record(details)
            if not normalized:
                continue
            self.portfolio_service.upsert_symbol(symbol, normalized)
            symbols_imported += 1
            if any(key in normalized for key in ("quantity", "shares", "costBasis", "cost_basis")):
                self.holdings_service.upsert_holding(symbol, normalized)
                holdings_imported += 1

        return {
            "symbolsImported": symbols_imported,
            "holdingsImported": holdings_imported,
            "symbols": self.portfolio_service.list_symbols(),
            "holdings": self.holdings_service.list_holdings(),
        }

    def import_file(self, filename: str, raw_bytes: bytes) -> dict[str, Any]:
        text = self._decode_text(raw_bytes)
        lower_name = filename.lower()

        if lower_name.endswith(".json"):
            return self._with_format(self.import_payload(self._parse_structured_text(text)), "json")

        if lower_name.endswith(".csv"):
            return self._with_format(self.import_csv(text), "csv")

        if lower_name.endswith(".txt"):
            return self._with_format(self.import_txt(text), "txt")

        try:
            return self._with_format(self.import_payload(self._parse_structured_text(text)), "json")
        except ValueError:
            return self._with_format(self.import_txt(text), "txt")

    def import_txt(self, text: str) -> dict[str, Any]:
        stripped = text.strip()
        if not stripped:
            raise ValueError("Text file is empty.")

        try:
            return self.import_payload(self._parse_structured_text(stripped))
        except ValueError:
            pass

        if self._looks_like_csv(stripped):
            return self.import_csv(stripped)

        records = self._parse_txt_blocks(stripped)
        if not records:
            records = self._parse_positional_lines(stripped)

        if not records:
            raise ValueError(self._parse_help_message())

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
            payload = self._normalize_symbol_record(
                {
                    "symbol": symbol.upper(),
                    "currentPrice": row.get("currentprice") or row.get("price"),
                    "targetPrice": row.get("targetprice") or row.get("target"),
                    "buyBelow": row.get("buybelow"),
                    "sellAbove": row.get("sellabove"),
                    "quantity": row.get("quantity") or row.get("shares"),
                    "costBasis": row.get("costbasis") or row.get("cost"),
                }
            )
            if not payload:
                continue
            result = self.import_payload({symbol.upper(): payload})
            imported["symbolsImported"] += result["symbolsImported"]
            imported["holdingsImported"] += result["holdingsImported"]

        return {
            **imported,
            "symbols": self.portfolio_service.list_symbols(),
            "holdings": self.holdings_service.list_holdings(),
        }

    def _parse_structured_text(self, text: str) -> dict[str, Any]:
        cleaned = self._strip_markdown_fences(text.strip())
        blob = self._extract_object_blob(cleaned) or cleaned

        for candidate in (blob, cleaned):
            for parser in (self._loads_json, self._loads_python_literal):
                try:
                    payload = parser(candidate)
                    if isinstance(payload, dict):
                        return payload
                except (json.JSONDecodeError, SyntaxError, ValueError):
                    continue

        raise ValueError("Could not parse structured text as JSON or Python dict.")

    def _parse_txt_blocks(self, text: str) -> dict[str, dict[str, Any]]:
        records: dict[str, dict[str, Any]] = {}
        current_symbol: str | None = None

        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("//"):
                continue

            line = re.sub(r"^\*\*(.+)\*\*$", r"\1", line)
            line = re.sub(r"^__(.+)__$", r"\1", line)

            symbol_kv = SYMBOL_KV.match(line)
            if symbol_kv:
                current_symbol = symbol_kv.group(1).upper()
                records.setdefault(current_symbol, {})
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
            mapped = self._map_field(field_key)
            if not mapped:
                continue

            value = self._clean_number(kv_match.group(2))
            if value is None:
                continue

            if current_symbol is None:
                continue

            records.setdefault(current_symbol, {})[mapped] = value

        return {symbol: details for symbol, details in records.items() if details}

    def _parse_positional_lines(self, text: str) -> dict[str, dict[str, Any]]:
        records: dict[str, dict[str, Any]] = {}
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            match = POSITIONAL_LINE.match(line)
            if not match:
                continue
            symbol = match.group(1).upper()
            current = self._clean_number(match.group(2))
            target = self._clean_number(match.group(3) or "")
            buy_below = self._clean_number(match.group(4) or "")
            sell_above = self._clean_number(match.group(5) or "")
            record = {}
            if current is not None:
                record["currentPrice"] = current
            if target is not None:
                record["targetPrice"] = target
            if buy_below is not None:
                record["buyBelow"] = buy_below
            if sell_above is not None:
                record["sellAbove"] = sell_above
            if record:
                records[symbol] = record
        return records

    def _normalize_symbol_record(self, details: dict[str, Any]) -> dict[str, Any]:
        normalized = {}
        mapping = {
            "currentPrice": ("currentPrice", "current_price", "price"),
            "targetPrice": ("targetPrice", "target_price", "target"),
            "buyBelow": ("buyBelow", "buy_below"),
            "sellAbove": ("sellAbove", "sell_above"),
            "quantity": ("quantity", "shares", "qty"),
            "costBasis": ("costBasis", "cost_basis", "cost"),
        }
        for target, keys in mapping.items():
            for key in keys:
                if key in details and details[key] not in (None, ""):
                    value = details[key]
                    if isinstance(value, (int, float)):
                        normalized[target] = float(value)
                    else:
                        parsed = self._clean_number(str(value))
                        if parsed is not None:
                            normalized[target] = parsed
                    break
        return normalized

    def _looks_like_csv(self, text: str) -> bool:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if len(lines) < 2:
            return False
        first = lines[0].lower()
        if ":" in first and not any(sep in first for sep in (",", "\t", ";", "|")):
            return False
        delimiter_present = any(sep in first for sep in (",", "\t", ";", "|"))
        return delimiter_present and ("symbol" in first or "ticker" in first)

    def _decode_text(self, raw_bytes: bytes) -> str:
        for encoding in ("utf-8-sig", "utf-16", "latin-1"):
            try:
                return raw_bytes.decode(encoding)
            except UnicodeDecodeError:
                continue
        return raw_bytes.decode("utf-8", errors="replace")

    def _strip_markdown_fences(self, text: str) -> str:
        fenced = re.search(r"```(?:json|javascript|txt)?\s*([\s\S]*?)```", text, re.I)
        if fenced:
            return fenced.group(1).strip()
        return text

    def _extract_object_blob(self, text: str) -> str | None:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            return text[start : end + 1]
        return None

    def _loads_json(self, text: str) -> dict[str, Any]:
        fixed = re.sub(r",\s*([}\]])", r"\1", text)
        payload = json.loads(fixed)
        if not isinstance(payload, dict):
            raise ValueError("JSON root must be an object.")
        return payload

    def _loads_python_literal(self, text: str) -> dict[str, Any]:
        payload = ast.literal_eval(text)
        if not isinstance(payload, dict):
            raise ValueError("Literal root must be an object.")
        return payload

    def _normalize_field_name(self, name: str) -> str:
        cleaned = re.sub(r"\([^)]*\)", "", name)
        return re.sub(r"\s+", " ", cleaned.strip().lower())

    def _map_field(self, field_key: str) -> str | None:
        if CAMEL_FIELD.match(field_key):
            return field_key
        camel = FIELD_ALIASES.get(field_key)
        if camel:
            return camel
        compact = field_key.replace(" ", "")
        if CAMEL_FIELD.match(compact):
            return compact
        return FIELD_ALIASES.get(compact)

    def _clean_number(self, value: str) -> float | None:
        if value is None:
            return None
        text = str(value).strip()
        if not text:
            return None

        if re.search(r"\d,\d", text) and text.count(",") == 1 and text.rfind(".") < text.rfind(","):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")

        cleaned = re.sub(r"[^\d.\-]", "", text)
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

    def _parse_help_message(self) -> str:
        return (
            "Could not parse text file. Supported formats: "
            "JSON/Python dict ({\"AAPL\": {\"currentPrice\": 170}}), "
            "symbol blocks (AAPL then Current Price: 170), "
            "Symbol: AAPL lines, or CSV with a symbol column."
        )
