import Constants from "expo-constants";
import { Platform } from "react-native";

import type { ApiConfig } from "./types";

const DEFAULT_BASE = "http://localhost:5001/api/v1";
const RENDER_BASE = "https://portfolio-dashboard-agent.onrender.com/api/v1";
const HEALTH_RETRIES = 3;
const HEALTH_RETRY_MS = 4000;
const DEFAULT_TIMEOUT_MS = 12000;
const NEWS_FEED_TIMEOUT_MS = 45000;
const FUNDAMENTALS_TIMEOUT_MS = 45000;

function pointsAtLocalhost(url: string): boolean {
  return /localhost|127\.0\.0\.1/i.test(url);
}

/** True when this client cannot use the dev machine's localhost API. */
function prefersRemoteApi(): boolean {
  if (Platform.OS === "ios") {
    // Only the iOS Simulator reports simulator: true; real devices do not.
    if (Constants.platform?.ios?.simulator === true) return false;
    return true;
  }
  if (Platform.OS === "android") {
    return Constants.isDevice;
  }
  return Constants.isDevice;
}

function resolveApiBase(envUrl?: string): string {
  const fromEnv = envUrl?.trim();
  const remote = prefersRemoteApi();

  if (fromEnv) {
    const base = fromEnv.replace(/\/$/, "");
    if (remote && pointsAtLocalhost(base)) return RENDER_BASE;
    return base;
  }

  return remote ? RENDER_BASE : DEFAULT_BASE;
}

export class ApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

export function getApiBaseUrl(): string {
  return resolveApiBase(process.env.EXPO_PUBLIC_API_BASE_URL);
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
  options: RequestInit & { timeoutMs?: number } = {},
): Promise<T> {
  const { timeoutMs = DEFAULT_TIMEOUT_MS, ...fetchOptions } = options;
  const base = getApiBaseUrl();
  const url = `${base}${path.startsWith("/") ? path : `/${path}`}`;
  const headers = new Headers(fetchOptions.headers);
  if (!headers.has("Content-Type") && fetchOptions.body) {
    headers.set("Content-Type", "application/json");
  }
  const devToken = process.env.EXPO_PUBLIC_MOBILE_DEV_TOKEN?.trim();
  if (devToken && !headers.has("Authorization")) {
    headers.set("Authorization", `Bearer ${devToken}`);
  }

  const res = await fetchWithTimeout(
    url,
    {
      ...fetchOptions,
      headers,
    },
    timeoutMs,
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
  fundamentals: () =>
    apiFetch<import("./types").FundamentalsFeed>("/fundamentals?includeNews=0", {
      timeoutMs: FUNDAMENTALS_TIMEOUT_MS,
    }),
  newsFeed: (newsLimit = 40) =>
    apiFetch<import("./types").NewsFeed>(
      `/news-feed?newsLimit=${newsLimit}&changesLimit=30`,
      { timeoutMs: NEWS_FEED_TIMEOUT_MS },
    ),
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
  inspector: (symbol: string, options?: { lite?: boolean }) => {
    const lite = options?.lite !== false;
    return apiFetch<import("./types").InspectorPayload>(
      `/symbols/${encodeURIComponent(symbol)}/inspector?includeNews=false&lite=${lite ? "1" : "0"}`,
    );
  },
  newsSentiment: (symbol: string) =>
    apiFetch<{
      symbol: string;
      newsSentiment: {
        sentiment?: string;
        detail?: string;
        count?: number;
      } | null;
    }>(`/symbols/${encodeURIComponent(symbol)}/news-sentiment`),
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
