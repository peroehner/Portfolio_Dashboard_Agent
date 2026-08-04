import type { Alert } from "@/lib/types";

function alertTypeKey(alert: Alert): string {
  return String(alert.type || alert.alert_type || "")
    .trim()
    .toLowerCase();
}

function fibIdentity(alert: Alert): string {
  const fib = String(alert.fibLevel || "").trim().toLowerCase();
  if (fib) return fib;
  const bold = (alert.message || "").match(/\*\*([^*]+)\*\*/)?.[1]?.trim().toLowerCase();
  if (bold) return bold;
  const ref = alert.referenceValue ?? alert.reference_value;
  if (ref != null && Number.isFinite(Number(ref))) {
    return `ref:${Math.round(Number(ref) * 100) / 100}`;
  }
  return "";
}

/**
 * Active-alerts list for symbol Summary: drop stale rows and collapse
 * duplicates of the same kind (e.g. repeated 38.2% Retracement Fibs).
 * Assumes API order: active first, newest first within status.
 */
export function dedupeActiveAlerts(alerts: Alert[] | null | undefined): Alert[] {
  if (!alerts?.length) return [];
  const active = alerts.filter((a) => (a.status || "active") === "active");
  const source = active.length ? active : alerts;

  const seen = new Set<string>();
  const out: Alert[] = [];
  for (const alert of source) {
    const type = alertTypeKey(alert);
    const fib = type.includes("fib") ? fibIdentity(alert) : "";
    const ref = alert.referenceValue ?? alert.reference_value;
    const refKey =
      ref != null && Number.isFinite(Number(ref))
        ? String(Math.round(Number(ref) * 100) / 100)
        : "";
    const key = fib ? `${type}|${fib}` : `${type}|${refKey || alert.id}`;
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(alert);
  }
  return out;
}
