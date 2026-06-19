import ast
import json
import re
from datetime import datetime
from typing import Any

from services.holdings_service import HoldingsService
from services.notes_service import NotesService
from services.portfolio_service import PortfolioService
from services.technical_service import TechnicalService

BLOCK_HEADER = re.compile(
    r"\[TECHNICAL ANALYSIS EXPORT:\s*([A-Z][A-Z0-9.\-]+)\s*\]",
    re.I,
)
PORTFOLIO_EXPORT = re.compile(r"\[PORTFOLIO EXPORT", re.I)
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
PURCHASE_LINE = re.compile(
    r"Purchased\s+([\d.,]+)\s+shares\s+on\s+([\d-]+)\s+@\s+([\d.,]+)",
    re.I,
)
DIVIDEND_LINE = re.compile(
    r"Estimate annual dividend income:\s*([\d.,]+)",
    re.I,
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
    "personal target": "targetPrice",
    "1y target": "analystTarget1y",
    "1y mean target": "analystTarget1y",
    "1y price target": "analystTarget1y",
    "price target": "analystTarget1y",
    "analyst target": "analystTarget1y",
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
    VALID_MODES = ("merge", "replace")

    def __init__(self):
        self.portfolio_service = PortfolioService()
        self.holdings_service = HoldingsService()
        self.technical_service = TechnicalService()
        self.notes_service = NotesService()

    def import_payload(self, payload: Any, mode: str = "merge") -> dict[str, Any]:
        if isinstance(payload, str):
            payload = self._parse_structured_text(payload)

        if not isinstance(payload, dict):
            raise ValueError("Import payload must be a JSON object.")

        import_mode, cleared_symbols = self._prepare_import(mode)
        symbols_imported = 0
        symbols_added = 0
        symbols_updated = 0
        symbols_skipped = 0
        holdings_imported = 0
        notes_imported = 0

        def apply_symbol(symbol: str, data: dict[str, Any]) -> None:
            nonlocal symbols_imported, symbols_added, symbols_updated, symbols_skipped
            nonlocal holdings_imported, notes_imported
            record = self._canonicalize_record(data)
            notes = record.pop("notes", None)
            outcome = self._import_symbol_record(symbol, record, import_mode)
            if outcome["skipped"]:
                symbols_skipped += 1
                return
            symbols_imported += 1
            if outcome["added"]:
                symbols_added += 1
            if outcome["updated"]:
                symbols_updated += 1
            if outcome["holding"]:
                holdings_imported += 1
            notes_imported += self._import_notes(symbol, notes, import_mode)

        for list_key in ("positions", "symbols", "holdings"):
            if list_key in payload and isinstance(payload[list_key], list):
                for item in payload[list_key]:
                    if not isinstance(item, dict) or not item.get("symbol"):
                        continue
                    apply_symbol(item["symbol"], item)

        for symbol, details in payload.items():
            if symbol in ("positions", "symbols", "holdings", "portfolio", "metadata"):
                continue
            if not isinstance(details, dict):
                continue
            normalized = self._normalize_symbol_record(details)
            if not normalized and "_technical" not in details and "notes" not in details:
                continue
            apply_symbol(symbol, details)

        return self._finalize_import(
            {
                "symbolsImported": symbols_imported,
                "symbolsAdded": symbols_added,
                "symbolsUpdated": symbols_updated,
                "symbolsSkipped": symbols_skipped,
                "holdingsImported": holdings_imported,
                "notesImported": notes_imported,
                "clearedSymbols": cleared_symbols,
            },
            import_mode,
        )

    def import_file(
        self,
        filename: str,
        raw_bytes: bytes,
        content_type: str | None = None,
        mode: str = "merge",
    ) -> dict[str, Any]:
        text = self._decode_text(raw_bytes)
        lower_name = (filename or "").lower()
        lower_type = (content_type or "").lower()

        if lower_name.endswith(".csv") or "csv" in lower_type:
            return self._with_format(self.import_csv(text, mode=mode), "csv")

        return self._with_format(self.import_txt(text, mode=mode), "txt")

    def import_txt(self, text: str, mode: str = "merge") -> dict[str, Any]:
        stripped = text.strip()
        if not stripped:
            raise ValueError("Text file is empty.")

        try:
            return self.import_payload(self._parse_structured_text(stripped), mode=mode)
        except ValueError:
            pass

        if self._is_technical_analysis_export(stripped):
            records = self._parse_technical_analysis_export(stripped)
            if records:
                return self.import_payload(records, mode=mode)

        records = self._parse_markdown_table(stripped)
        if records:
            return self.import_payload(records, mode=mode)

        if self._looks_like_csv(stripped):
            return self.import_csv(stripped, mode=mode)

        records = self._parse_txt_blocks(stripped)
        if not records:
            records = self._parse_positional_lines(stripped)
        if not records:
            records = self._parse_inline_assignments(stripped)

        if not records:
            raise ValueError(self._parse_help_message())

        return self.import_payload(records, mode=mode)

    def import_csv(self, text: str, mode: str = "merge") -> dict[str, Any]:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if len(lines) < 2:
            raise ValueError("CSV must include a header row and at least one data row.")

        delimiter = self._detect_csv_delimiter(lines[0])
        headers = [part.strip().lower() for part in lines[0].split(delimiter)]
        symbol_idx = self._header_index(headers, ("symbol", "ticker"))
        if symbol_idx is None:
            raise ValueError("CSV must include a symbol or ticker column.")

        import_mode, cleared_symbols = self._prepare_import(mode)
        imported = {
            "symbolsImported": 0,
            "symbolsAdded": 0,
            "symbolsUpdated": 0,
            "symbolsSkipped": 0,
            "holdingsImported": 0,
            "clearedSymbols": cleared_symbols,
        }
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
                    "quantity": row.get("quantity") or row.get("shares") or row.get("qty"),
                    "costBasis": (
                        row.get("costbasis")
                        or row.get("cost")
                        or row.get("avgcost")
                        or row.get("averagecost")
                        or row.get("avg cost")
                        or row.get("avg_cost")
                    ),
                    "purchaseDate": (
                        row.get("purchasedate")
                        or row.get("purchase_date")
                        or row.get("purchase date")
                        or row.get("entrydate")
                        or row.get("date")
                    ),
                    "accountName": (
                        row.get("account")
                        or row.get("accountname")
                        or row.get("account name")
                    ),
                    "annualDividend": row.get("annualdividend") or row.get("dividend"),
                }
            )
            if not payload:
                continue
            outcome = self._import_symbol_record(symbol.upper(), payload, import_mode)
            if outcome["skipped"]:
                imported["symbolsSkipped"] += 1
                continue
            imported["symbolsImported"] += 1
            if outcome["added"]:
                imported["symbolsAdded"] += 1
            if outcome["updated"]:
                imported["symbolsUpdated"] += 1
            if outcome["holding"]:
                imported["holdingsImported"] += 1

        return self._finalize_import(imported, import_mode)

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

            purchase_match = PURCHASE_LINE.search(line)
            if purchase_match and current_symbol:
                record = records.setdefault(current_symbol, {})
                record["quantity"] = self._clean_number(purchase_match.group(1))
                record["purchaseDate"] = purchase_match.group(2)
                record["costBasis"] = self._clean_number(purchase_match.group(3))
                continue

            dividend_match = DIVIDEND_LINE.search(line)
            if dividend_match and current_symbol:
                records.setdefault(current_symbol, {})["annualDividend"] = self._clean_number(
                    dividend_match.group(1)
                )
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

    def _is_technical_analysis_export(self, text: str) -> bool:
        upper = text.upper()
        return "[TECHNICAL ANALYSIS EXPORT:" in upper or PORTFOLIO_EXPORT.search(text) is not None

    def _parse_technical_analysis_export(self, text: str) -> dict[str, dict[str, Any]]:
        records: dict[str, dict[str, Any]] = {}
        parts = BLOCK_HEADER.split(text)
        # split returns [preamble, symbol, body, symbol, body, ...]
        for index in range(1, len(parts), 2):
            symbol = parts[index].upper()
            body = parts[index + 1] if index + 1 < len(parts) else ""
            record: dict[str, Any] = {}

            current_match = re.search(r"Current Price:\s*([\d.,]+)", body, re.I)
            if current_match:
                record["currentPrice"] = self._clean_number(current_match.group(1))

            personal_target_match = re.search(
                r"Personal Target:\s*([\d.,]+)",
                body,
                re.I,
            )
            if personal_target_match:
                record["targetPrice"] = self._clean_number(personal_target_match.group(1))

            target_match = re.search(r"1Y Mean Target estimate:\s*([\d.,]+)", body, re.I)
            if target_match:
                record["analystTarget1y"] = self._clean_number(target_match.group(1))

            purchase_match = PURCHASE_LINE.search(body)
            if purchase_match:
                record["quantity"] = self._clean_number(purchase_match.group(1))
                record["purchaseDate"] = purchase_match.group(2)
                record["costBasis"] = self._clean_number(purchase_match.group(3))

            dividend_match = DIVIDEND_LINE.search(body)
            if dividend_match:
                record["annualDividend"] = self._clean_number(dividend_match.group(1))

            technical = self.technical_service.parse_export_body(body)
            if technical:
                record["_technical"] = technical

            normalized = self._normalize_symbol_record(record)
            if normalized or technical:
                payload = normalized or {}
                if technical:
                    payload["_technical"] = technical
                records[symbol] = payload

        return records

    def _parse_markdown_table(self, text: str) -> dict[str, dict[str, Any]]:
        lines = [line.strip() for line in text.splitlines() if "|" in line]
        if len(lines) < 2:
            return {}

        rows = []
        for line in lines:
            if re.match(r"^\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)+\|?$", line):
                continue
            cells = [cell.strip() for cell in line.strip("|").split("|")]
            if cells:
                rows.append(cells)

        if len(rows) < 2:
            return {}

        headers = [self._normalize_field_name(cell) for cell in rows[0]]
        symbol_idx = self._header_index(headers, ("symbol", "ticker"))
        if symbol_idx is None:
            return {}

        records: dict[str, dict[str, Any]] = {}
        for row in rows[1:]:
            if symbol_idx >= len(row):
                continue
            symbol = row[symbol_idx].upper()
            if not re.match(r"^[A-Z][A-Z0-9.\-]{0,9}$", symbol):
                continue
            payload: dict[str, Any] = {}
            for idx, header in enumerate(headers):
                if idx == symbol_idx or idx >= len(row):
                    continue
                mapped = self._map_field(header)
                if not mapped:
                    continue
                value = self._clean_number(row[idx])
                if value is not None:
                    payload[mapped] = value
            normalized = self._normalize_symbol_record(payload)
            if normalized:
                records[symbol] = normalized
        return records

    def _parse_inline_assignments(self, text: str) -> dict[str, dict[str, Any]]:
        records: dict[str, dict[str, Any]] = {}
        assignment = re.compile(
            r"\b([A-Z][A-Z0-9.\-]{0,9})\b.*?((?:currentPrice|targetPrice|buyBelow|sellAbove|quantity|shares|costBasis)\s*[:=]\s*[\d.,$€£+\-]+(?:\s*,?\s*(?:currentPrice|targetPrice|buyBelow|sellAbove|quantity|shares|costBasis)\s*[:=]\s*[\d.,$€£+\-]+)*)",
            re.I,
        )
        for match in assignment.finditer(text):
            symbol = match.group(1).upper()
            chunk = match.group(2)
            payload: dict[str, Any] = {}
            for part in re.finditer(
                r"(currentPrice|targetPrice|buyBelow|sellAbove|quantity|shares|costBasis)\s*[:=]\s*([\d.,$€£+\-]+)",
                chunk,
                re.I,
            ):
                key = part.group(1)
                if key.lower() == "shares":
                    key = "quantity"
                value = self._clean_number(part.group(2))
                if value is not None:
                    payload[key if key != "quantity" else "quantity"] = value
            normalized = self._normalize_symbol_record(payload)
            if normalized:
                records[symbol] = normalized
        return records

    def _normalize_symbol_record(self, details: dict[str, Any]) -> dict[str, Any]:
        normalized = {}
        mapping = {
            "currentPrice": ("currentPrice", "current_price", "price"),
            "targetPrice": ("targetPrice", "target_price"),
            "analystTarget1y": ("analystTarget1y", "analyst_target_1y", "target1y"),
            "buyBelow": ("buyBelow", "buy_below"),
            "sellAbove": ("sellAbove", "sell_above"),
            "quantity": ("quantity", "shares", "qty"),
            "costBasis": ("costBasis", "cost_basis", "cost"),
            "annualDividend": ("annualDividend", "annual_dividend", "dividend"),
            "purchaseDate": ("purchaseDate", "purchase_date", "entryDate", "entry_date"),
            "accountName": ("accountName", "account_name", "account"),
        }
        text_fields = {"purchaseDate", "accountName"}
        for target, keys in mapping.items():
            for key in keys:
                if key in details and details[key] not in (None, ""):
                    value = details[key]
                    if target == "purchaseDate":
                        normalized[target] = self._parse_date_flexible(value)
                    elif target == "accountName":
                        normalized[target] = str(value).strip()
                    elif isinstance(value, (int, float)):
                        normalized[target] = float(value)
                    else:
                        parsed = self._clean_number(str(value))
                        if parsed is not None:
                            normalized[target] = parsed
                    break
        return normalized

    @staticmethod
    def _detect_csv_delimiter(header_line: str) -> str:
        """Pick the most frequent of ';', tab, or ',' in the header row."""
        counts = {sep: header_line.count(sep) for sep in (";", "\t", ",")}
        best = max(counts, key=lambda sep: counts[sep])
        return best if counts[best] > 0 else ","

    @staticmethod
    def _parse_date_flexible(value: Any) -> str:
        """Normalize unambiguous date formats to ISO (YYYY-MM-DD); pass through otherwise.

        Handles '19.06.26' / '19.06.2026' (dot dates are unambiguously day-first
        / European), ISO dates, and year-first slash dates. Two-digit years map
        via %y (26 -> 2026). Ambiguous month/day slash dates (e.g. '01/02/2025')
        are intentionally left untouched rather than guessed.
        """
        text = str(value).strip()
        if not text:
            return text
        for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d.%m.%y", "%Y/%m/%d"):
            try:
                return datetime.strptime(text, fmt).strftime("%Y-%m-%d")
            except ValueError:
                continue
        return text[:10]

    def _looks_like_csv(self, text: str) -> bool:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if len(lines) < 2:
            return False
        first = lines[0].lower()
        if ":" in first and not any(sep in first for sep in (",", "\t", ";", "|")):
            return False
        delimiter_present = any(sep in first for sep in (",", "\t", ";"))
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
        fixed = self._fix_js_object(text)
        fixed = re.sub(r",\s*([}\]])", r"\1", fixed)
        payload = json.loads(fixed)
        if not isinstance(payload, dict):
            raise ValueError("JSON root must be an object.")
        return payload

    def _fix_js_object(self, text: str) -> str:
        """Quote bare object keys: { AAPL: { currentPrice: 1 } }."""
        return re.sub(r'([{\[,]\s*)([A-Za-z_][A-Za-z0-9_]*)\s*:', r'\1"\2":', text)

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

    def _canonicalize_record(self, data: dict[str, Any]) -> dict[str, Any]:
        """Return a shallow copy with tolerant aliases mapped to canonical keys.

        Lets minimal exports (symbol/shares/purchaseDate/avgCost) and richer
        records flow through upsert_symbol/upsert_holding unchanged.
        """
        if not isinstance(data, dict):
            return {}
        record = dict(data)

        def first(*keys):
            for key in keys:
                if key in record and record[key] not in (None, ""):
                    return record[key]
            return None

        if "costBasis" not in record and "cost_basis" not in record:
            avg = first("avgCost", "averageCost", "avg_cost", "cost")
            if avg is not None:
                record["costBasis"] = avg
        if "quantity" not in record:
            qty = first("shares", "qty")
            if qty is not None:
                record["quantity"] = qty
        if "accountName" not in record and "account_name" not in record:
            account = first("account", "accountName", "account_name")
            if account is not None:
                record["accountName"] = account
        return record

    def _import_notes(self, symbol: str, notes: Any, mode: str) -> int:
        if not isinstance(notes, list) or not notes:
            return 0
        symbol = symbol.upper()
        existing_keys = set()
        if mode != "replace":
            for note in self.notes_service.list_notes(symbol):
                existing_keys.add((note.get("date"), note.get("source"), note.get("text")))
        count = 0
        for note in notes:
            if not isinstance(note, dict):
                continue
            text = note.get("text") or note.get("note")
            if not text or not str(text).strip():
                continue
            date = note.get("date") or note.get("note_date")
            source = note.get("source")
            key = (date, source, text)
            if key in existing_keys:
                continue
            self.notes_service.add_note(
                symbol,
                {"text": str(text), "date": date, "source": source or "import"},
            )
            existing_keys.add(key)
            count += 1
        return count

    def _import_symbol_record(
        self,
        symbol: str,
        data: dict[str, Any],
        mode: str,
    ) -> dict[str, bool]:
        symbol = symbol.upper()
        existing = self.portfolio_service.get_symbol(symbol) is not None

        technical = data.pop("_technical", None)
        self.portfolio_service.upsert_symbol(symbol, data)
        if technical:
            self.technical_service.upsert_snapshot(symbol, technical)
        holding = False
        if any(
            key in data
            for key in (
                "quantity",
                "shares",
                "costBasis",
                "cost_basis",
                "purchaseDate",
                "purchase_date",
            )
        ):
            self.holdings_service.upsert_holding(symbol, data)
            holding = True

        return {
            "skipped": False,
            "added": not existing,
            "updated": existing,
            "holding": holding,
        }

    def _prepare_import(self, mode: str) -> tuple[str, int]:
        import_mode = self._normalize_mode(mode)
        cleared = 0
        if import_mode == "replace":
            cleared = self.portfolio_service.clear_portfolio()
        return import_mode, cleared

    def _normalize_mode(self, mode: str | None) -> str:
        value = (mode or "merge").strip().lower()
        aliases = {
            "merge": "merge",
            "update": "merge",
            "upsert": "merge",
            "replace": "replace",
            "overwrite": "replace",
            "full": "replace",
        }
        normalized = aliases.get(value)
        if normalized is None:
            raise ValueError("Import mode must be 'merge' or 'replace'.")
        return normalized

    def _finalize_import(
        self,
        counts: dict[str, Any],
        mode: str,
    ) -> dict[str, Any]:
        return {
            **counts,
            "mode": mode,
            "symbols": self.portfolio_service.list_symbols(),
            "holdings": self.holdings_service.list_holdings(),
        }

    def _with_format(self, result: dict[str, Any], fmt: str) -> dict[str, Any]:
        return {**result, "format": fmt}

    def _parse_help_message(self) -> str:
        return (
            "Could not parse text file. Supported formats: "
            "JSON/Python dict ({\"AAPL\": {\"currentPrice\": 170}}), "
            "symbol blocks (AAPL then Current Price: 170), "
            "Symbol: AAPL lines, or CSV with a symbol column."
        )
