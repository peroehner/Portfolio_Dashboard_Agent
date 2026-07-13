import Constants from "expo-constants";

import type { ApiConfig } from "./types";

const DEFAULT_BASE = "http://localhost:5001/api/v1";
const HEALTH_RETRIES = 3;
const HEALTH_RETRY_MS = 4000;
const FETCH_TIMEOUT_MS = 12000;

export class ApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

export function getApiBaseUrl(): string {
  const fromEnv = process.env.EXPO_PUBLIC_API_BASE_URL?.trim();
  if (fromEnv) return fromEnv.replace(/\/$/, "");
  return DEFAULT_BASE;
}

export function getApiHostLabel(): string {
  try {
    const url = new URL(getApiBaseUrl());
    return url.host;
  } catch {
    return getApiBaseUrl();
  }
}

async function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function parseJson<T>(res: Response): Promise<T> {
  const text = await res.text();
  if (!text) return {} as T;
  try {
    return JSON.parse(text) as T;
  } catch {
    throw new ApiError(text || res.statusText, res.status);
  }
}

async function fetchWithTimeout(
  url: string,
  options: RequestInit,
  timeoutMs: number,
): Promise<Response> {
  const controller = new AbortController();
  const id = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(url, {
      ...options,
      signal: controller.signal,
    });
  } catch (err) {
    if (err instanceof Error && err.name === "AbortError") {
      throw new ApiError(`Request timed out after ${Math.round(timeoutMs / 1000)}s`, 408);
    }
    throw err;
  } finally {
    clearTimeout(id);
  }
}

export async function apiFetch<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const base = getApiBaseUrl();
  const url = `${base}${path.startsWith("/") ? path : `/${path}`}`;
  const headers = new Headers(options.headers);
  if (!headers.has("Content-Type") && options.body) {
    headers.set("Content-Type", "application/json");
  }
  const devToken = process.env.EXPO_PUBLIC_MOBILE_DEV_TOKEN?.trim();
  if (devToken && !headers.has("Authorization")) {
    headers.set("Authorization", `Bearer ${devToken}`);
  }

  const res = await fetchWithTimeout(
    url,
    {
      ...options,
      headers,
    },
    FETCH_TIMEOUT_MS,
  );

  const data = await parseJson<{ error?: string; message?: string } & T>(res);
  if (!res.ok) {
    throw new ApiError(
      data.error || data.message || res.statusText || "Request failed",
      res.status,
    );
  }
  return data;
}

export async function wakeApi(): Promise<void> {
  let lastError: Error | null = null;
  for (let attempt = 0; attempt < HEALTH_RETRIES; attempt += 1) {
    try {
      await apiFetch<{ status?: string }>("/health");
      return;
    } catch (err) {
      lastError = err instanceof Error ? err : new Error(String(err));
      if (attempt < HEALTH_RETRIES - 1) {
        await sleep(HEALTH_RETRY_MS);
      }
    }
  }
  throw lastError ?? new Error("Could not reach API");
}

export async function fetchConfig(): Promise<ApiConfig> {
  return apiFetch<ApiConfig>("/config");
}

export const api = {
  wake: wakeApi,
  config: fetchConfig,
  overview: () => apiFetch<import("./types").Overview>("/overview"),
  portfolio: () => apiFetch<{ symbols: import("./types").PortfolioSymbol[] }>("/portfolio"),
  holdings: () => apiFetch<{ holdings: import("./types").Holding[] }>("/holdings"),
  newsFeed: (newsLimit = 40) =>
    apiFetch<import("./types").NewsFeed>(`/news-feed?newsLimit=${newsLimit}&changesLimit=30`),
  alerts: (status = "active") =>
    apiFetch<{ alerts: import("./types").Alert[] }>(`/alerts?status=${status}`),
  dismissAlert: (id: number) =>
    apiFetch(`/alerts/${id}/dismiss`, { method: "POST" }),
  updateSymbol: (symbol: string, data: Partial<import("./types").PortfolioSymbol>) =>
    apiFetch<import("./types").PortfolioSymbol>(`/symbols/${encodeURIComponent(symbol)}`, {
      method: "PUT",
      body: JSON.stringify(data),
    }),
  addNote: (symbol: string, data: import("./types").Note) =>
    apiFetch<import("./types").Note>(`/symbols/${encodeURIComponent(symbol)}/notes`, {
      method: "POST",
      body: JSON.stringify(data),
    }),
  inspector: (symbol: string) =>
    apiFetch<import("./types").InspectorPayload>(
      `/symbols/${encodeURIComponent(symbol)}/inspector?includeNews=false&lite=1`,
    ),
  assessmentsOverview: () =>
    apiFetch<{ assessments: import("./types").Assessment[] }>("/assessments/overview"),
  sync: () => apiFetch("/sync", { method: "POST" }),
};

export function showApiHostInDev(): boolean {
  return (
    process.env.EXPO_PUBLIC_SHOW_API_HOST === "1" ||
    Constants.expoConfig?.extra?.showApiHost === true
  );
}
