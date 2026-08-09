"""Tax & Trim proposal + order-book capture (shared web/mobile).

Candidate building and Match Loss allocation for Simulation Tax & Trim.
Loss/trim scoring is delegated to harvest_score (same curves as dashboard.html).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from services.assessment_service import AssessmentService
from services.harvest_score import loss_score, residual_loss_pct, trim_score
from services.holdings_service import HoldingsService
from services.portfolio_intent import harvest_intent_lean, resolve_intent
from services.portfolio_service import PortfolioService

MAX_TRIM_POSITIONS = 10
SAI_ACTION_WEIGHT = {"sell": 20, "watch": 12, "hold": 4, "buy": 0}
SAI_CONF_BONUS = {"high": 3, "medium": 2, "low": 1}


def _f(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        amount = float(value)
    except (TypeError, ValueError):
        return None
    return amount if amount == amount else None  # NaN guard


def eval_trade_leg(price: Any, shares: Any, side: str) -> dict[str, Any] | None:
    p = _f(price)
    if p is None:
        return None
    sh = _f(shares) or 0.0
    if sh > 0:
        buy = True
    elif sh < 0:
        buy = False
    else:
        buy = side == "below"
    return {
        "side": side,
        "price": p,
        "qty": abs(sh),
        "buy": buy,
        "qtyNotSet": not sh,
    }


def sell_plan_qty(symbol_row: dict[str, Any]) -> float:
    qty = 0.0
    for leg in (
        eval_trade_leg(symbol_row.get("tradeBelowPrice"), symbol_row.get("tradeBelowShares"), "below"),
        eval_trade_leg(symbol_row.get("tradeAbovePrice"), symbol_row.get("tradeAboveShares"), "above"),
    ):
        if leg and not leg["buy"] and leg["qty"]:
            qty += leg["qty"]
    return qty


def buy_plan_qty(symbol_row: dict[str, Any]) -> float:
    qty = 0.0
    for leg in (
        eval_trade_leg(symbol_row.get("tradeBelowPrice"), symbol_row.get("tradeBelowShares"), "below"),
        eval_trade_leg(symbol_row.get("tradeAbovePrice"), symbol_row.get("tradeAboveShares"), "above"),
    ):
        if leg and leg["buy"] and leg["qty"]:
            qty += leg["qty"]
    return qty


def sell_threshold_price(symbol_row: dict[str, Any]) -> float | None:
    notional = 0.0
    qty = 0.0
    for leg in (
        eval_trade_leg(symbol_row.get("tradeBelowPrice"), symbol_row.get("tradeBelowShares"), "below"),
        eval_trade_leg(symbol_row.get("tradeAbovePrice"), symbol_row.get("tradeAboveShares"), "above"),
    ):
        if not leg or leg["buy"] or not (leg["qty"] > 0) or not (leg["price"] > 0):
            continue
        notional += leg["price"] * leg["qty"]
        qty += leg["qty"]
    if not (qty > 0):
        return None
    return notional / qty


def exec_price_info(symbol_row: dict[str, Any], pricing_mode: str) -> dict[str, Any]:
    spot = _f(symbol_row.get("currentPrice"))
    if pricing_mode == "threshold":
        thr = sell_threshold_price(symbol_row)
        if thr is not None and thr > 0:
            return {"price": thr, "source": "threshold"}
    if spot is not None and spot > 0:
        return {"price": spot, "source": "spot"}
    return {"price": None, "source": None}


def intent_for_row(symbol_row: dict[str, Any]) -> dict[str, Any]:
    """Resolve portfolio Intent for a tax/trim candidate row."""
    held = float(symbol_row.get("quantity") or 0)
    buy = buy_plan_qty(symbol_row)
    sell = sell_plan_qty(symbol_row)
    return resolve_intent(
        held=held,
        buy_qty=buy,
        sell_qty=sell,
        buy_price=None,
        sell_price=None,
        override=symbol_row.get("intentOverride") or symbol_row.get("intent_override"),
    )


def sai_weight(action: str | None, confidence: str | None) -> float:
    act = str(action or "hold").lower()
    weight = float(SAI_ACTION_WEIGHT.get(act, 0))
    conf = str(confidence or "medium").lower()
    if act in ("sell", "watch") and conf in SAI_CONF_BONUS:
        weight += SAI_CONF_BONUS[conf]
    return weight


def allocate_winner_trims(
    selected: list[dict[str, Any]],
    loss_pool_amount: float,
    match_loss_pool: bool,
) -> dict[str, Any]:
    loss_pool = max(0.0, float(loss_pool_amount or 0))
    selected_trim_pool = sum(max(0.0, float(row.get("netGainsMax") or 0)) for row in selected)
    target = min(loss_pool, selected_trim_pool) if match_loss_pool else selected_trim_pool
    if not (target > 0) or not selected:
        return {
            "picks": [],
            "offsetGain": 0.0,
            "remainingLoss": loss_pool if match_loss_pool else 0.0,
            "selectedTrimPool": selected_trim_pool,
            "allocTarget": target,
            "matchLossPool": bool(match_loss_pool),
        }

    pool = sorted(
        selected,
        key=lambda c: (float(c.get("trimScore") or 0), float(c.get("netGainsMax") or 0)),
        reverse=True,
    )[:MAX_TRIM_POSITIONS]
    weights = [max(1.0, float(c.get("trimScore") or 0)) for c in pool]
    sum_w = sum(weights) or 1.0
    shares_by_symbol = {c["symbol"]: 0.0 for c in pool}

    def total_gain() -> float:
        return sum(
            shares_by_symbol[c["symbol"]] * float(c["gainPerShare"])
            for c in pool
            if float(c.get("gainPerShare") or 0) > 0
        )

    for i, cand in enumerate(pool):
        gps = float(cand.get("gainPerShare") or 0)
        if not (gps > 0):
            continue
        want = (target * weights[i]) / sum_w
        shares = int(want / gps)
        if shares <= 0 and want >= gps * 0.5 and not match_loss_pool:
            shares = 1
        if shares <= 0 and want >= gps and match_loss_pool:
            shares = 1
        shares = max(0, min(int(cand.get("sellQtyMax") or 0), shares))
        shares_by_symbol[cand["symbol"]] = float(shares)

    gained = total_gain()
    if gained > target + 1e-6:
        scale = target / gained
        for cand in pool:
            sh = shares_by_symbol[cand["symbol"]]
            shares_by_symbol[cand["symbol"]] = float(max(0, int(sh * scale)))
        gained = total_gain()

    remaining = max(0.0, target - gained)
    for cand in sorted(
        pool,
        key=lambda c: (float(c.get("trimScore") or 0), float(c.get("netGainsMax") or 0)),
        reverse=True,
    ):
        if not (remaining > 0):
            break
        gps = float(cand.get("gainPerShare") or 0)
        if not (gps > 0):
            continue
        used = shares_by_symbol[cand["symbol"]]
        room = float(cand.get("sellQtyMax") or 0) - used
        if room <= 0:
            continue
        add = min(int(room), int(remaining / gps))
        if add <= 0:
            continue
        shares_by_symbol[cand["symbol"]] = used + add
        remaining = max(0.0, remaining - add * gps)

    picks = []
    for cand in pool:
        suggest = shares_by_symbol[cand["symbol"]]
        if suggest <= 0:
            continue
        gps = float(cand["gainPerShare"])
        exec_price = _f(cand.get("execPrice")) or _f(cand.get("currentPrice")) or 0.0
        picks.append(
            {
                **cand,
                "suggestShares": suggest,
                "suggestGain": suggest * gps,
                "suggestCash": suggest * exec_price,
            }
        )
    picks.sort(
        key=lambda r: (float(r.get("trimScore") or 0), float(r.get("suggestGain") or 0)),
        reverse=True,
    )
    offset = sum(float(r["suggestGain"]) for r in picks)
    return {
        "picks": picks,
        "offsetGain": offset,
        "remainingLoss": max(0.0, loss_pool - offset) if match_loss_pool else 0.0,
        "selectedTrimPool": selected_trim_pool,
        "allocTarget": target,
        "matchLossPool": bool(match_loss_pool),
    }


class TaxTrimService:
    def __init__(self) -> None:
        self.portfolio_service = PortfolioService()
        self.holdings_service = HoldingsService()
        self.assessment_service = AssessmentService()

    def _merged_rows(self) -> list[dict[str, Any]]:
        symbols = {s["symbol"]: s for s in self.portfolio_service.list_symbols()}
        holdings = {h["symbol"]: h for h in self.holdings_service.list_holdings()}
        assessments = {
            a["symbol"]: a for a in self.assessment_service.latest_overview() if a.get("symbol")
        }
        total_mv = sum(
            float(h.get("marketValue") or 0) for h in holdings.values() if h.get("marketValue")
        )
        rows = []
        for symbol, holding in holdings.items():
            qty = float(holding.get("quantity") or 0)
            if qty <= 0:
                continue
            sym = symbols.get(symbol) or {"symbol": symbol}
            rec = assessments.get(symbol) or {}
            price = _f(holding.get("currentPrice")) or _f(sym.get("currentPrice"))
            analyst = _f(holding.get("analystTarget1y")) or _f(sym.get("analystTarget1y"))
            analyst_upside = _f(holding.get("analystUpsidePct"))
            if analyst_upside is None and analyst is not None and price and price > 0:
                analyst_upside = ((analyst - price) / price) * 100.0
            personal = _f(holding.get("personalTarget")) or _f(sym.get("targetPrice"))
            personal_upside = _f(holding.get("personalUpsidePct"))
            if personal_upside is None and personal is not None and price and price > 0:
                personal_upside = ((personal - price) / price) * 100.0
            mv = _f(holding.get("marketValue"))
            weight = (mv / total_mv * 100.0) if mv and total_mv > 0 else None
            rows.append(
                {
                    **sym,
                    "symbol": symbol,
                    "currentPrice": price,
                    "holding": holding,
                    "costBasis": _f(holding.get("costBasis")),
                    "quantity": qty,
                    "gainPct": _f(holding.get("gainPct")),
                    "unrealizedGain": _f(holding.get("unrealizedGain")),
                    "marketValue": mv,
                    "weightPct": weight,
                    "analystTarget1y": analyst,
                    "analystUpsidePct": analyst_upside,
                    "personalTarget": personal,
                    "personalUpsidePct": personal_upside,
                    "recommendation": {
                        "action": rec.get("action"),
                        "confidence": rec.get("confidence"),
                    },
                    "techStance": rec.get("techStance"),
                }
            )
        return rows

    def build_loss_candidates(
        self,
        rows: list[dict[str, Any]],
        pricing_mode: str,
        scoped_symbols: set[str] | None = None,
    ) -> dict[str, Any]:
        candidates = []
        for row in rows:
            symbol = str(row["symbol"]).upper()
            if scoped_symbols is not None and symbol not in scoped_symbols:
                continue
            gain_pct = _f(row.get("gainPct"))
            if gain_pct is None or gain_pct >= 0:
                continue
            exec_info = exec_price_info(row, pricing_mode)
            exec_price = exec_info["price"]
            cost = _f(row.get("costBasis"))
            if exec_price is None or cost is None:
                continue
            gain_per_share = exec_price - cost
            if not (gain_per_share < 0):
                continue
            loss_per_share = -gain_per_share
            held = float(row.get("quantity") or 0)
            sell_qty = sell_plan_qty(row)
            max_shares = min(sell_qty, held) if sell_qty > 0 else held
            if max_shares <= 0:
                continue
            upside = _f(row.get("analystUpsidePct"))
            ls = loss_score(gain_pct, upside)
            residual = residual_loss_pct(gain_pct, upside)
            has_sell_plan = sell_qty > 0
            is_trim = held > sell_qty if has_sell_plan else max_shares < held
            net_loss = loss_per_share * max_shares
            rec = row.get("recommendation") or {}
            sw = sai_weight(rec.get("action"), rec.get("confidence"))
            intent = intent_for_row(row)
            lean, lean_note = harvest_intent_lean(
                intent_code=intent.get("code"),
                is_trim=is_trim,
                held=held,
                sell_qty=max_shares,
            )
            score = 25 + ls
            if has_sell_plan:
                score += 20
            if is_trim:
                score += 10
            score += min(15.0, net_loss / 5000.0)
            score += sw
            score += lean
            candidates.append(
                {
                    "symbol": symbol,
                    "held": held,
                    "sellQtyMax": max_shares,
                    "sellPlanCap": sell_qty if has_sell_plan else None,
                    "netLossMax": round(net_loss, 2),
                    "lossPerShare": round(loss_per_share, 4),
                    "cashGenerated": round(max_shares * exec_price, 2),
                    "execPrice": round(exec_price, 2),
                    "execSource": exec_info["source"],
                    "pricingMode": pricing_mode,
                    "gainPct": round(gain_pct, 2),
                    "lossPct": round(abs(gain_pct), 2),
                    "analystUpsidePct": round(upside, 2) if upside is not None else None,
                    "residualLossPct": round(residual, 2) if residual is not None else None,
                    "hasSellPlan": has_sell_plan,
                    "isTrim": is_trim,
                    "score": round(score, 2),
                    "lossScore": round(ls, 2),
                    "saiWeight": sw,
                    "intentLean": lean,
                    "intent": intent.get("code"),
                    "intentLabel": intent.get("label"),
                    "intentNote": lean_note,
                    "saiAction": rec.get("action") or "—",
                    "saiConfidence": rec.get("confidence") or "—",
                    "techBias": row.get("techStance") or "—",
                    "currentPrice": round(float(row.get("currentPrice") or 0), 2),
                }
            )
        candidates.sort(
            key=lambda c: (c["score"], c["netLossMax"], c.get("residualLossPct") or 0, c["lossPct"]),
            reverse=True,
        )
        return {"candidates": candidates}

    def build_trim_candidates(
        self,
        rows: list[dict[str, Any]],
        pricing_mode: str,
        scoped_symbols: set[str] | None = None,
    ) -> dict[str, Any]:
        candidates = []
        for row in rows:
            symbol = str(row["symbol"]).upper()
            if scoped_symbols is not None and symbol not in scoped_symbols:
                continue
            gain_pct = _f(row.get("gainPct"))
            unrealized = _f(row.get("unrealizedGain"))
            if not (
                (gain_pct is not None and gain_pct > 0)
                or (unrealized is not None and unrealized > 0)
            ):
                continue
            exec_info = exec_price_info(row, pricing_mode)
            exec_price = exec_info["price"]
            cost = _f(row.get("costBasis"))
            if exec_price is None or cost is None:
                continue
            gain_per_share = exec_price - cost
            if not (gain_per_share > 0):
                continue
            held = float(row.get("quantity") or 0)
            sell_qty = sell_plan_qty(row)
            buy_qty = buy_plan_qty(row)
            max_shares = min(sell_qty, held) if sell_qty > 0 else held
            if max_shares <= 0:
                continue
            parts = trim_score(
                analyst_upside_pct=_f(row.get("analystUpsidePct")),
                personal_upside_pct=_f(row.get("personalUpsidePct")),
                peak_pct=None,
                weight_pct=_f(row.get("weightPct")),
                buy_qty=buy_qty,
                sell_qty=sell_qty,
                held=held,
            )
            net_gains = gain_per_share * max_shares
            has_sell_plan = sell_qty > 0
            is_trim = held > sell_qty if has_sell_plan else max_shares < held
            trim = parts["trimScore"]
            intent = intent_for_row(row)
            lean, lean_note = harvest_intent_lean(
                intent_code=intent.get("code"),
                is_trim=is_trim,
                held=held,
                sell_qty=max_shares,
            )
            score = trim + min(15.0, net_gains / 5000.0) + lean
            rec = row.get("recommendation") or {}
            candidates.append(
                {
                    "symbol": symbol,
                    "held": held,
                    "sellQtyMax": max_shares,
                    "sellPlanCap": sell_qty if has_sell_plan else None,
                    "buyPlanQty": buy_qty,
                    "netGainsMax": round(net_gains, 2),
                    "gainPerShare": round(gain_per_share, 4),
                    "cashGenerated": round(max_shares * exec_price, 2),
                    "execPrice": round(exec_price, 2),
                    "execSource": exec_info["source"],
                    "pricingMode": pricing_mode,
                    "gainPct": round(gain_pct, 2) if gain_pct is not None else None,
                    "weightPct": round(float(row["weightPct"]), 2)
                    if row.get("weightPct") is not None
                    else None,
                    "analystUpsidePct": round(float(row["analystUpsidePct"]), 2)
                    if row.get("analystUpsidePct") is not None
                    else None,
                    "personalUpsidePct": round(float(row["personalUpsidePct"]), 2)
                    if row.get("personalUpsidePct") is not None
                    else None,
                    "headroomPct": round(parts["headroomPct"], 2),
                    "hasSellPlan": has_sell_plan,
                    "isTrim": is_trim,
                    "score": round(score, 2),
                    "trimScore": round(trim + lean, 2),
                    "intentLean": lean,
                    "intent": intent.get("code"),
                    "intentLabel": intent.get("label"),
                    "intentNote": lean_note,
                    "saiAction": rec.get("action") or "—",
                    "saiConfidence": rec.get("confidence") or "—",
                    "techBias": row.get("techStance") or "—",
                    "currentPrice": round(float(row.get("currentPrice") or 0), 2),
                }
            )
        candidates.sort(
            key=lambda c: (c["trimScore"], c["netGainsMax"], c.get("gainPct") or 0),
            reverse=True,
        )
        return {"candidates": candidates}

    def build_proposal(
        self,
        *,
        pricing_mode: str = "current",
        loss_score_threshold: float = 0,
        trim_score_threshold: float = 0,
        match_loss_pool: bool = True,
        selected_symbols: list[str] | None = None,
    ) -> dict[str, Any]:
        mode = "threshold" if pricing_mode == "threshold" else "current"
        # None = no client scope (all holdings). [] = explicit empty scope.
        if selected_symbols is None:
            scope: set[str] | None = None
        else:
            scope = {str(s).upper() for s in selected_symbols if s}
        rows = self._merged_rows()
        loss_sells = self.build_loss_candidates(rows, mode, scope)
        threshold = max(0.0, float(loss_score_threshold or 0))
        selected_loss = [
            row for row in loss_sells["candidates"] if float(row.get("lossScore") or 0) >= threshold
        ]
        selected_loss_pool = sum(max(0.0, float(r.get("netLossMax") or 0)) for r in selected_loss)

        winner_trims = self.build_trim_candidates(rows, mode, scope)
        trim_threshold = max(0.0, float(trim_score_threshold or 0))
        selected_trims = [
            row
            for row in winner_trims["candidates"]
            if float(row.get("trimScore") or 0) >= trim_threshold
        ]
        alloc = allocate_winner_trims(selected_trims, selected_loss_pool, match_loss_pool)

        all_loss_pool = sum(
            max(0.0, float(r.get("netLossMax") or 0)) for r in loss_sells["candidates"]
        )
        all_trim_pool = sum(
            max(0.0, float(r.get("netGainsMax") or 0)) for r in winner_trims["candidates"]
        )
        selected_trim_pool = sum(
            max(0.0, float(r.get("netGainsMax") or 0)) for r in selected_trims
        )

        return {
            "pricingMode": mode,
            "lossScoreThreshold": threshold,
            "trimScoreThreshold": trim_threshold,
            "matchLossPool": bool(match_loss_pool),
            "lossPool": round(selected_loss_pool, 2),
            "allCandidatePool": round(all_loss_pool, 2),
            "allTrimCandidatePool": round(all_trim_pool, 2),
            "selectedTrimPool": round(selected_trim_pool, 2),
            "offsetGain": round(float(alloc["offsetGain"]), 2),
            "remainingLoss": round(float(alloc["remainingLoss"]), 2),
            "allocTarget": round(float(alloc["allocTarget"]), 2),
            "lossSells": {
                "candidates": loss_sells["candidates"],
                "selectedCount": len(selected_loss),
                "candidateCount": len(loss_sells["candidates"]),
            },
            "winnerTrims": {
                "candidates": winner_trims["candidates"],
                "selectedCount": len(selected_trims),
                "candidateCount": len(winner_trims["candidates"]),
            },
            "picks": alloc["picks"],
            "scopedSymbols": sorted(scope) if scope is not None else None,
        }

    def build_order_book(self, proposal: dict[str, Any] | None = None, **kwargs: Any) -> dict[str, Any]:
        proposal = proposal or self.build_proposal(**kwargs)
        threshold = max(0.0, float(proposal.get("lossScoreThreshold") or 0))
        loss_orders = [
            {
                "side": "sell",
                "kind": "tax_loss",
                "symbol": row["symbol"],
                "shares": float(row.get("sellQtyMax") or 0),
                "limit": row.get("execPrice"),
                "execSource": row.get("execSource"),
                "estLoss": row.get("netLossMax"),
                "estCash": row.get("cashGenerated"),
                "lossScore": row.get("lossScore"),
                "held": row.get("held"),
            }
            for row in (proposal.get("lossSells") or {}).get("candidates") or []
            if float(row.get("lossScore") or 0) >= threshold
        ]
        trim_orders = [
            {
                "side": "sell",
                "kind": "winner_trim",
                "symbol": row["symbol"],
                "shares": float(row.get("suggestShares") or 0),
                "limit": row.get("execPrice"),
                "execSource": row.get("execSource"),
                "estGain": row.get("suggestGain"),
                "estCash": row.get("suggestCash"),
                "trimScore": row.get("trimScore"),
                "held": row.get("held"),
                "maxTrim": row.get("sellQtyMax"),
            }
            for row in proposal.get("picks") or []
        ]
        orders = loss_orders + trim_orders
        return {
            "v": 1,
            "type": "tax_trim_order_book",
            "capturedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "settings": {
                "pricingMode": proposal.get("pricingMode"),
                "lossScoreThreshold": proposal.get("lossScoreThreshold"),
                "trimScoreThreshold": proposal.get("trimScoreThreshold"),
                "matchLossPool": proposal.get("matchLossPool"),
                "selectedSymbols": proposal.get("scopedSymbols") or [],
            },
            "summary": {
                "lossPool": proposal.get("lossPool"),
                "offsetGain": proposal.get("offsetGain"),
                "remainingLoss": proposal.get("remainingLoss"),
                "selectedLossCount": len(loss_orders),
                "proposedTrimCount": len(trim_orders),
                "orderCount": len(orders),
                "estSellCash": round(sum(float(o.get("estCash") or 0) for o in orders), 2),
            },
            "orders": orders,
            "proposal": proposal,
        }
