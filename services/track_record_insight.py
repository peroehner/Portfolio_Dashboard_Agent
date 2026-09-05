"""Rule-based Agent Signal Record self-assessment (Trust / Discount / Use).

Shared by live Summary (`GET /track-record`) and the weekly snapshot worker.
Not an LLM — grades Bet-S-Hit / Hit / Follow with min-N gates so live and
weekly briefings stay identical.
"""

from __future__ import annotations

from typing import Any


def _decided(bucket: dict[str, Any] | None) -> int:
    if not bucket:
        return 0
    return int(bucket.get("wins") or 0) + int(bucket.get("losses") or 0)


def _strength(bucket: dict[str, Any] | None) -> float | None:
    if not bucket:
        return None
    if bucket.get("calibratedHitRate") is not None:
        return float(bucket["calibratedHitRate"])
    if bucket.get("hitRate") is not None:
        return float(bucket["hitRate"])
    return None


def _grade(rate: float | None) -> str | None:
    if rate is None:
        return None
    if rate >= 70:
        return "outstanding"
    if rate >= 55:
        return "good"
    if rate < 45:
        return "weak"
    return "mixed"


def _rollup(buckets: list[dict[str, Any]]) -> dict[str, Any]:
    count = wins = losses = neutrals = 0
    ret_sum = adj_sum = ret_n = 0.0
    cal_sum = cal_n = 0.0
    for bucket in buckets:
        count += int(bucket.get("count") or 0)
        wins += int(bucket.get("wins") or 0)
        losses += int(bucket.get("losses") or 0)
        neutrals += int(bucket.get("neutrals") or 0)
        n = int(bucket.get("count") or 0)
        if bucket.get("avgReturn") is not None and n:
            ret_sum += float(bucket["avgReturn"]) * n
            ret_n += n
        if bucket.get("avgReturnAdj") is not None and n:
            adj_sum += float(bucket["avgReturnAdj"]) * n
        decided = int(bucket.get("wins") or 0) + int(bucket.get("losses") or 0)
        if bucket.get("calibratedHitRate") is not None and decided:
            cal_sum += float(bucket["calibratedHitRate"]) * decided
            cal_n += decided
    decided = wins + losses
    return {
        "count": count,
        "wins": wins,
        "losses": losses,
        "neutrals": neutrals,
        "hitRate": round(wins / decided * 100, 1) if decided else None,
        "avgReturn": round(ret_sum / ret_n, 2) if ret_n else None,
        "avgReturnAdj": round(adj_sum / ret_n, 2) if ret_n else None,
        "calibratedHitRate": round(cal_sum / cal_n, 1) if cal_n else None,
    }


def _find_label(buckets: list[dict[str, Any]], label: str) -> dict[str, Any] | None:
    needle = label.lower()
    for bucket in buckets:
        if str(bucket.get("label") or "").lower() == needle:
            return bucket
    return None


def _find_confidence(buckets: list[dict[str, Any]], conf: str) -> dict[str, Any] | None:
    needle = conf.lower()
    for bucket in buckets:
        key = str(bucket.get("confidence") or bucket.get("label") or "").lower()
        if key == needle:
            return bucket
    return None


def build_insight(summary: dict[str, Any] | None) -> dict[str, Any]:
    """Return structured Trust / Discount / Use briefing for a track-record summary."""
    summary = summary or {}
    overall = summary.get("overall") or {}
    by_label = summary.get("byLabel") or []
    by_conf = summary.get("byConfidence") or []

    recos = [b for b in by_label if b.get("kind") == "recommendation"]
    patterns = [b for b in by_label if b.get("kind") == "pattern"]
    confluence = [b for b in by_label if b.get("kind") == "confluence"]

    decided = _decided(overall)
    hit = overall.get("hitRate")
    adj = overall.get("avgReturnAdj")
    str_hit = overall.get("calibratedHitRate")
    if str_hit is not None:
        str_hit = float(str_hit)
    if hit is not None:
        hit = float(hit)
    if adj is not None:
        adj = float(adj)

    sell = _find_label(recos, "sell")
    buy = _find_label(recos, "buy")
    bearish = _find_label(confluence, "bearish")
    bullish = _find_label(confluence, "bullish")
    sai_roll = _rollup(recos)
    pat_roll = _rollup(patterns)
    conf_roll = _rollup(confluence)

    sell_str = _strength(sell)
    buy_str = _strength(buy)
    sai_str = _strength(sai_roll)
    pat_str = _strength(pat_roll)
    conf_str = _strength(conf_roll)
    bear_str = _strength(bearish)
    bull_str = _strength(bullish)

    trust: list[str] = []
    discount: list[str] = []
    use: list[str] = []

    if sell and _decided(sell) >= 5 and sell_str is not None:
        grade = _grade(sell_str)
        if grade in ("outstanding", "good"):
            trust.append(f"SAI Sell ({sell_str:.0f}% Bet-S-Hit)")
    if _decided(sai_roll) >= 10 and sai_str is not None:
        grade = _grade(sai_str)
        if grade in ("outstanding", "good"):
            trust.append(f"SAI overall ({sai_str:.0f}%)")
    if _decided(pat_roll) >= 8 and pat_str is not None:
        grade = _grade(pat_str)
        if grade in ("outstanding", "good"):
            trust.append(f"Patterns ({pat_str:.0f}%)")
    if bullish and _decided(bullish) >= 5 and bull_str is not None:
        grade = _grade(bull_str)
        if grade in ("outstanding", "good"):
            trust.append(f"Bullish Tech bias ({bull_str:.0f}%)")
    if bearish and _decided(bearish) >= 5 and bear_str is not None:
        grade = _grade(bear_str)
        if grade in ("outstanding", "good"):
            trust.append(f"Bearish Tech bias ({bear_str:.0f}%)")

    high = _find_confidence(by_conf, "high")
    medium = _find_confidence(by_conf, "medium")
    low = _find_confidence(by_conf, "low")
    high_str = _strength(high)
    med_str = _strength(medium)
    high_n = _decided(high)
    med_n = _decided(medium)

    # Soft spot the live UI missed: High Conf underperforming Medium.
    if (
        high is not None
        and medium is not None
        and high_str is not None
        and med_str is not None
        and high_n >= 5
        and med_n >= 5
        and med_str - high_str >= 8
    ):
        discount.append(
            f"SAI High Conf ({high_str:.0f}% Bet-S-Hit) trails Medium ({med_str:.0f}%)"
        )
        use.append("Prefer Medium-Conf SAI over High until High earns its label")
    elif high is not None and high_str is not None and high_n >= 5 and _grade(high_str) == "weak":
        discount.append(f"SAI High Conf ({high_str:.0f}% Bet-S-Hit)")

    if bearish and _decided(bearish) >= 5 and bear_str is not None:
        grade = _grade(bear_str)
        if grade in ("weak", "mixed"):
            discount.append(f"Bearish Tech bias ({bear_str:.0f}% Bet-S-Hit)")
    if (
        _decided(conf_roll) >= 8
        and conf_str is not None
        and (
            _grade(conf_str) == "weak"
            or (pat_str is not None and conf_str <= pat_str - 8)
            or (sai_str is not None and conf_str <= sai_str - 8)
        )
    ):
        if not any("Tech bias" in item for item in discount):
            discount.append(f"Tech bias overall ({conf_str:.0f}%)")
    if buy and _decided(buy) >= 10 and buy.get("hitRate") is not None and float(buy["hitRate"]) < 45:
        discount.append(f"SAI Buy plain Hit ({float(buy['hitRate']):.0f}%)")
    if str_hit is not None and hit is not None and decided >= 15 and str_hit - hit <= -5:
        discount.append(
            f"high-Conf/Score bets (Bet-S-Hit {str_hit:.0f}% ≪ Hit {hit:.0f}%)"
        )

    if str_hit is not None and hit is not None and decided >= 15 and str_hit - hit >= 5:
        if not any("Medium-Conf" in item for item in use):
            use.append("Prefer higher Conf·Score SAI when Bet-S-Hit leads Hit")
    if (
        high is not None
        and low is not None
        and high.get("hitRate") is not None
        and low.get("hitRate") is not None
        and _decided(high) >= 5
        and _decided(low) >= 5
        and float(high["hitRate"]) - float(low["hitRate"]) >= 10
        and not any("Medium-Conf" in item for item in use)
    ):
        use.append(
            f"Weight High-Conf SAI ({float(high['hitRate']):.0f}% hit) over Low "
            f"({float(low['hitRate']):.0f}%)"
        )
    if (
        bullish
        and bearish
        and bull_str is not None
        and bear_str is not None
        and _decided(bullish) >= 5
        and _decided(bearish) >= 5
        and bull_str - bear_str >= 10
    ):
        use.append("Treat bullish Tech bias as the edge; do not mirror weak bearish")
    if (
        sell
        and sell.get("avgReturnAdj") is not None
        and float(sell["avgReturnAdj"]) > 0
        and sell.get("avgReturn") is not None
        and float(sell["avgReturn"]) < 0
    ):
        use.append("Read Sell on Follow, not Price — Price understates working sells")
    elif (
        adj is not None
        and overall.get("avgReturn") is not None
        and abs(adj - float(overall["avgReturn"])) >= 1.5
        and adj > float(overall["avgReturn"])
    ):
        use.append("Favor Follow over Price when judging call quality")

    if not use and trust:
        use.append("Size into trusted lanes; keep size modest elsewhere")
    elif not use and discount:
        use.append("Wait for clearer edge before sizing into discounted lanes")
    elif not use:
        use.append("Keep sizing flat until Hit / Bet-S-Hit separate by lane")

    if not trust and not discount and decided < 8:
        return {
            "trust": [],
            "discount": [],
            "use": [],
            "tone": "empty",
            "headline": None,
        }

    tone = "neutral"
    if discount and trust:
        tone = "warn"
    elif discount:
        tone = "warn"
    elif trust or (hit is not None and hit >= 55 and adj is not None and adj > 0):
        tone = "ok"
    elif hit is not None and hit < 40:
        tone = "warn"

    headline_bits = []
    if trust:
        headline_bits.append(f"Trust {trust[0]}")
    if discount:
        headline_bits.append(f"Discount {discount[0]}")
    if use:
        headline_bits.append(f"Use: {use[0]}")

    return {
        "trust": trust[:3],
        "discount": discount[:3],
        "use": use[:2],
        "tone": tone,
        "headline": " · ".join(headline_bits) if headline_bits else None,
    }
