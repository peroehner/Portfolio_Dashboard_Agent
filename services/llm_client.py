import json
import os
import re
import urllib.error
import urllib.request
from typing import Any


class LLMClient:
    VALID_ACTIONS = {"buy", "sell", "hold", "watch"}
    VALID_CONFIDENCE = {"high", "medium", "low"}

    def __init__(self):
        self.mode = os.environ.get("ASSESSMENT_MODE", "auto").strip().lower()
        self.provider = os.environ.get("LLM_PROVIDER", "").strip().lower()
        self.gemini_api_key = os.environ.get("GEMINI_API_KEY", os.environ.get("GOOGLE_API_KEY", "")).strip()
        self.openai_api_key = os.environ.get("OPENAI_API_KEY", "").strip()
        self.gemini_model = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")
        self.openai_model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")

    def active_provider(self) -> str:
        if self.mode == "rules":
            return "rules"
        if self.mode == "openai" or self._should_use_openai():
            return "openai"
        if self.mode == "gemini" or self._should_use_gemini():
            return "gemini"
        return "rules"

    def generate_assessment(self, context: dict[str, Any]) -> dict[str, Any]:
        provider = self.active_provider()
        if provider == "openai":
            return self._normalize(self._call_openai(context), provider="openai")
        if provider == "gemini":
            return self._normalize(self._call_gemini(context), provider="gemini")
        return self._normalize(self._rule_based(context), provider="rules")

    def _should_use_openai(self) -> bool:
        if self.mode == "rules":
            return False
        if self.mode == "openai":
            return bool(self.openai_api_key)
        if self.mode == "gemini":
            return False
        return self.provider == "openai" or (not self.provider and bool(self.openai_api_key))

    def _should_use_gemini(self) -> bool:
        if self.mode == "rules":
            return False
        if self.mode == "gemini":
            return bool(self.gemini_api_key)
        if self.mode == "openai":
            return False
        return self.provider == "gemini" or (not self.provider and bool(self.gemini_api_key))

    def _call_openai(self, context: dict[str, Any]) -> dict[str, Any]:
        payload = {
            "model": self.openai_model,
            "messages": [
                {"role": "system", "content": self._system_prompt()},
                {"role": "user", "content": self._user_prompt(context)},
            ],
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
        }
        response = self._post_json(
            "https://api.openai.com/v1/chat/completions",
            payload,
            headers={"Authorization": f"Bearer {self.openai_api_key}"},
        )
        content = response["choices"][0]["message"]["content"]
        return json.loads(content)

    def _call_gemini(self, context: dict[str, Any]) -> dict[str, Any]:
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.gemini_model}:generateContent?key={self.gemini_api_key}"
        )
        payload = {
            "contents": [{"parts": [{"text": self._system_prompt() + "\n\n" + self._user_prompt(context)}]}],
            "generationConfig": {
                "temperature": 0.2,
                "responseMimeType": "application/json",
            },
        }
        response = self._post_json(url, payload)
        content = response["candidates"][0]["content"]["parts"][0]["text"]
        return json.loads(content)

    def _rule_based(self, context: dict[str, Any]) -> dict[str, Any]:
        price = context.get("currentPrice")
        buy_below = context.get("buyBelow")
        sell_above = context.get("sellAbove")
        target = context.get("targetPrice")
        alerts = context.get("alerts", [])
        notes = context.get("notes", [])

        action = "hold"
        confidence = "medium"
        factors = []

        alert_types = {alert["type"] for alert in alerts}
        if "sell_above" in alert_types or (sell_above is not None and price is not None and price >= sell_above):
            action = "sell"
            confidence = "high"
            factors.append("Price is at or above your sell-above threshold.")
        elif "buy_below" in alert_types or (buy_below is not None and price is not None and price <= buy_below):
            action = "buy"
            confidence = "high"
            factors.append("Price is at or below your buy-below threshold.")
        elif "fib_proximity" in alert_types:
            action = "watch"
            confidence = "medium"
            factors.append("Price is near a key Fibonacci level.")
        elif "screener_upside" in alert_types:
            action = "watch"
            confidence = "medium"
            factors.append("Stock screens with substantial upside to target.")

        note_snippets = [note["text"] for note in notes[:3]]
        if note_snippets:
            factors.append(f"Personal notes considered: {' | '.join(note_snippets)}")

        if target and price and target > price and action == "hold":
            upside = (target - price) / price * 100
            if upside > 30:
                action = "watch"
                factors.append(f"Target implies {upside:.1f}% upside.")

        rationale = (
            f"{context['symbol']} assessment based on your thresholds, alerts, and notes. "
            + " ".join(factors or ["No major trigger; maintain current positioning."])
        )

        return {
            "action": action,
            "confidence": confidence,
            "rationale": rationale,
            "factors": factors or ["No active triggers."],
        }

    def _system_prompt(self) -> str:
        return (
            "You are a portfolio assistant. Use the user's personal notes, price thresholds, "
            "alerts, and Fibonacci levels to produce a concise trade recommendation. "
            "Respond only with JSON using keys: action, confidence, rationale, factors. "
            "action must be one of: buy, sell, hold, watch. "
            "confidence must be one of: high, medium, low. "
            "factors must be an array of short strings."
        )

    def _user_prompt(self, context: dict[str, Any]) -> str:
        return (
            "Assess this symbol for a trade recommendation.\n\n"
            f"Context JSON:\n{json.dumps(context, indent=2)}"
        )

    def _normalize(self, result: dict[str, Any], provider: str) -> dict[str, Any]:
        action = str(result.get("action", "hold")).strip().lower()
        confidence = str(result.get("confidence", "medium")).strip().lower()
        if action not in self.VALID_ACTIONS:
            action = "hold"
        if confidence not in self.VALID_CONFIDENCE:
            confidence = "medium"

        factors = result.get("factors", [])
        if isinstance(factors, str):
            factors = [factors]
        if not isinstance(factors, list):
            factors = []

        rationale = str(result.get("rationale", "")).strip()
        if not rationale:
            rationale = "No rationale provided."

        return {
            "action": action,
            "confidence": confidence,
            "rationale": rationale,
            "factors": [str(item) for item in factors],
            "provider": provider,
        }

    def _post_json(self, url: str, payload: dict[str, Any], headers: dict[str, str] | None = None) -> dict[str, Any]:
        body = json.dumps(payload).encode("utf-8")
        request_headers = {"Content-Type": "application/json"}
        if headers:
            request_headers.update(headers)

        req = urllib.request.Request(url, data=body, headers=request_headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=60) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"LLM request failed ({exc.code}): {detail}") from exc

    @staticmethod
    def extract_json(text: str) -> dict[str, Any]:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            raise ValueError("No JSON object found in LLM response.")
        return json.loads(match.group(0))
