import json
from typing import Any

from services.holdings_service import HoldingsService
from services.portfolio_service import PortfolioService


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
            return self.import_payload(json.loads(text))

        if lower_name.endswith(".csv"):
            return self.import_csv(text)

        try:
            return self.import_payload(json.loads(text))
        except json.JSONDecodeError as exc:
            raise ValueError("Unsupported file format. Use JSON or CSV.") from exc

    def import_csv(self, text: str) -> dict[str, Any]:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if len(lines) < 2:
            raise ValueError("CSV must include a header row and at least one data row.")

        headers = [part.strip().lower() for part in lines[0].split(",")]
        symbol_idx = self._header_index(headers, ("symbol", "ticker"))
        if symbol_idx is None:
            raise ValueError("CSV must include a symbol or ticker column.")

        imported = {"symbolsImported": 0, "holdingsImported": 0}
        for line in lines[1:]:
            values = [part.strip() for part in line.split(",")]
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

    def _header_index(self, headers: list[str], names: tuple[str, ...]) -> int | None:
        for name in names:
            if name in headers:
                return headers.index(name)
        return None
