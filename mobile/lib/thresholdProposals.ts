import type { InspectorPayload, PortfolioSymbol } from "@/lib/types";

export interface FibLevelOption {
  label: string;
  price: number;
}

export interface ThresholdProposals {
  buy: number | null;
  sell: number | null;
  buyNote: string;
  sellNote: string;
}

/** Fib / swing ladder for threshold suggestions (parity with web Target). */
export function targetFibLevels(data?: InspectorPayload | null): FibLevelOption[] {
  const imported = data?.importedFibLevels;
  if (imported?.length) {
    return imported
      .filter((level) => level.price != null && Number.isFinite(Number(level.price)))
      .map((level) => ({
        label: String(level.label || level.shortLabel || "").trim() || "Level",
        price: Number(level.price),
      }));
  }

  const fib = data?.fib;
  if (!fib) return [];
  const levels: FibLevelOption[] = [];
  if (fib.swingLow != null && Number.isFinite(Number(fib.swingLow))) {
    levels.push({ label: "Swing Low", price: Number(fib.swingLow) });
  }
  for (const level of fib.levels || []) {
    if (level.price == null || !Number.isFinite(Number(level.price))) continue;
    levels.push({
      label: String(level.label || "").trim() || "Fib",
      price: Number(level.price),
    });
  }
  if (fib.swingHigh != null && Number.isFinite(Number(fib.swingHigh))) {
    levels.push({ label: "Swing High", price: Number(fib.swingHigh) });
  }
  return levels;
}

/** Suggest Trade @ Below / Above prices from Fib + assessment (web proposeThresholds). */
export function proposeThresholds(
  quote?: PortfolioSymbol | null,
  data?: InspectorPayload | null,
): ThresholdProposals {
  const price = Number(quote?.currentPrice);
  const levels = targetFibLevels(data);
  if (!Number.isFinite(price) || price <= 0 || !levels.length) {
    return { buy: null, sell: null, buyNote: "", sellNote: "" };
  }

  const sorted = [...levels].sort((a, b) => a.price - b.price);
  const below = sorted.filter((level) => level.price < price);
  const above = sorted.filter((level) => level.price > price);
  const rec = data?.recommendation;
  const action = String(rec?.action || "hold").toLowerCase();
  const sentiment = String(rec?.sentiment || "neutral").toLowerCase();

  let buy: number | null = null;
  let buyNote = "";
  const support =
    below.find((level) => String(level.label).includes("61.8")) ||
    below.find((level) => String(level.label).includes("50")) ||
    below.find((level) => String(level.label).toLowerCase().includes("low")) ||
    below[below.length - 1];
  if (support) {
    buy = support.price;
    buyNote = `${support.label} support`;
    if (action !== "buy" && action !== "watch" && sentiment === "bullish") {
      buyNote += " · Bullish note sentiment";
    }
  }

  let sell: number | null = null;
  let sellNote = "";
  const target = Number(quote?.targetPrice);
  if (action === "sell") {
    const resistance = above[0] || sorted[sorted.length - 1];
    if (resistance && resistance.price > price) {
      sell = resistance.price;
      sellNote = `${resistance.label} · Assessment: sell`;
    }
  } else if (Number.isFinite(target) && target > price) {
    sell = target;
    sellNote = "Personal target";
  } else {
    const resistance =
      above.find((level) => String(level.label).toLowerCase().includes("high")) ||
      above[above.length - 1];
    if (resistance) {
      sell = resistance.price;
      sellNote = `${resistance.label} resistance`;
    }
  }

  return { buy, sell, buyNote, sellNote };
}
