/** Shared Tax & Trim Order Book CSV layout (web dashboard mirrors this). */

export type OrderBookCsvOrder = {
  side?: string;
  kind?: string;
  symbol?: string;
  shares?: number | null;
  limit?: number | null;
  estLoss?: number | null;
  estGain?: number | null;
  estCash?: number | null;
  lossScore?: number | null;
  trimScore?: number | null;
  held?: number | null;
  maxTrim?: number | null;
};

export type OrderBookCsvBook = {
  orders?: OrderBookCsvOrder[] | null;
};

export const ORDER_BOOK_CSV_HEADERS = [
  "Action",
  "Kind",
  "Symbol",
  "Score",
  "Trade Shares",
  "Limit",
  "Gain est",
  "Loss est",
  "Cash est",
  "Shares left",
  "MaxTrim",
] as const;

function csvEscape(value: unknown): string {
  const s = value == null ? "" : String(value);
  return /[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

function finite(value: unknown): number | null {
  if (value == null || value === "") return null;
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}

/** Limit / share price: $24.12 */
export function csvPrice(value: unknown): string {
  const n = finite(value);
  if (n == null) return "";
  return `$${n.toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

/** Row money amounts: $12,940.50 */
export function csvMoney2(value: unknown): string {
  const n = finite(value);
  if (n == null) return "";
  return `$${n.toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

/** Totals: $24,356 (no cents) */
export function csvMoney0(value: unknown): string {
  const n = finite(value);
  if (n == null) return "";
  return `$${Math.round(n).toLocaleString("en-US")}`;
}

/** Score truncated to 1 decimal: 32.1 */
export function csvScore1(value: unknown): string {
  const n = finite(value);
  if (n == null) return "";
  return (Math.round(n * 10) / 10).toFixed(1);
}

function orderScore(order: OrderBookCsvOrder): number | null {
  if (order.kind === "tax_loss") return finite(order.lossScore);
  if (order.kind === "winner_trim") return finite(order.trimScore);
  return finite(order.lossScore) ?? finite(order.trimScore);
}

function sharesLeft(order: OrderBookCsvOrder): string {
  const held = finite(order.held);
  const shares = finite(order.shares) ?? 0;
  if (held == null) return "";
  const left = Math.max(0, held - shares);
  return left % 1 === 0 ? String(left) : left.toFixed(2);
}

function tradeShares(order: OrderBookCsvOrder): string {
  const n = finite(order.shares);
  if (n == null) return "";
  return n % 1 === 0 ? String(n) : n.toFixed(2);
}

function maxTrim(order: OrderBookCsvOrder): string {
  const n = finite(order.maxTrim);
  if (n == null) return "";
  return n % 1 === 0 ? String(n) : n.toFixed(2);
}

function actionLabel(side: string | undefined): string {
  const s = String(side || "").trim();
  if (!s) return "";
  return s.charAt(0).toUpperCase() + s.slice(1).toLowerCase();
}

export function orderBookToCsv(book: OrderBookCsvBook | null | undefined): string {
  const lines = [ORDER_BOOK_CSV_HEADERS.join(",")];
  let totalGain = 0;
  let totalLoss = 0;
  let totalCash = 0;
  let hasGain = false;
  let hasLoss = false;
  let hasCash = false;

  for (const order of book?.orders || []) {
    const gain = finite(order.estGain);
    const loss = finite(order.estLoss);
    const cash = finite(order.estCash);
    if (gain != null) {
      totalGain += gain;
      hasGain = true;
    }
    if (loss != null) {
      totalLoss += loss;
      hasLoss = true;
    }
    if (cash != null) {
      totalCash += cash;
      hasCash = true;
    }

    lines.push(
      [
        actionLabel(order.side),
        order.kind || "",
        order.symbol || "",
        csvScore1(orderScore(order)),
        tradeShares(order),
        csvPrice(order.limit),
        gain != null ? csvMoney2(gain) : "",
        loss != null ? csvMoney2(loss) : "",
        cash != null ? csvMoney2(cash) : "",
        sharesLeft(order),
        maxTrim(order),
      ]
        .map(csvEscape)
        .join(","),
    );
  }

  lines.push(
    [
      "Totals",
      "",
      "",
      "",
      "",
      "",
      hasGain ? csvMoney0(totalGain) : "",
      hasLoss ? csvMoney0(totalLoss) : "",
      hasCash ? csvMoney0(totalCash) : "",
      "",
      "",
    ]
      .map(csvEscape)
      .join(","),
  );

  return `${lines.join("\n")}\n`;
}

export function orderBookStamp(iso?: string | null): string {
  const d = iso ? new Date(iso) : new Date();
  if (Number.isNaN(d.getTime())) return "orderbook";
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}-${p(d.getHours())}${p(d.getMinutes())}`;
}
