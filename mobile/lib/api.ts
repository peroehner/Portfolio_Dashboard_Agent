import Constants from "expo-constants";
import { Platform } from "react-native";

import type { ApiConfig } from "./types";

const DEFAULT_BASE = "http://localhost:5001/api/v1";
const RENDER_BASE = "https://portfolio-dashboard-agent.onrender.com/api/v1";
const HEALTH_RETRIES = 3;
const HEALTH_RETRY_MS = 4000;
const DEFAULT_TIMEOUT_MS = 12000;
const OVERVIEW_TIMEOUT_MS = 45000;
const NEWS_FEED_TIMEOUT_MS = 45000;
const FUNDAMENTALS_TIMEOUT_MS = 45000;
const NOTE_SAVE_TIMEOUT_MS = 45000;
/** Coalesce first authenticated reads after login (Summary + stars race). */
const PORTFOLIO_WARM_TTL_MS = 20000;

/** Shared in-flight wake so auth + first tab don't stampede /health. */
let wakeInFlight: Promise<void> | null = null;

type PortfolioPayload = { symbols: import("./types").PortfolioSymbol[] };
let portfolioWarm:
  | { at: number; promise: Promise<PortfolioPayload> }
  | null = null;

/** Per-user Google mobile session token (preferred over shared MOBILE_DEV_TOKEN). */
let accessToken: string | null = null;

export function setAccessToken(token: string | null): void {
  accessToken = token?.trim() || null;
  if (!accessToken) {
    portfolioWarm = null;
    wakeInFlight = null;
  }
}

export function getAccessToken(): string | null {
  return accessToken;
}

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

export function isTimeoutApiError(err: unknown): err is ApiError {
  return err instanceof ApiError && err.status === 408;
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

/** Origin without /api/v1 — used for /auth/mobile/* routes. */
export function getApiOrigin(): string {
  const base = getApiBaseUrl().replace(/\/api\/v1\/?$/, "");
  return base || getApiBaseUrl();
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
    const trimmed = text.trim();
    if (trimmed.startsWith("<!") || trimmed.toLowerCase().startsWith("<html")) {
      throw new ApiError(
        res.status === 405
          ? "API method not available — restart/redeploy the server with the latest build."
          : `Server returned HTML (${res.status}). Check API host / deploy.`,
        res.status,
      );
    }
    throw new ApiError(text.slice(0, 200) || res.statusText, res.status);
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

function applyAuthHeader(headers: Headers): void {
  if (headers.has("Authorization")) return;
  if (accessToken) {
    headers.set("Authorization", `Bearer ${accessToken}`);
    return;
  }
  // Shared simulator token only — never prefer over a real user session.
  const devToken = process.env.EXPO_PUBLIC_MOBILE_DEV_TOKEN?.trim();
  if (devToken) {
    headers.set("Authorization", `Bearer ${devToken}`);
  }
}

export async function apiFetch<T>(
  path: string,
  options: RequestInit & { timeoutMs?: number; absoluteUrl?: boolean } = {},
): Promise<T> {
  const { timeoutMs = DEFAULT_TIMEOUT_MS, absoluteUrl = false, ...fetchOptions } = options;
  const base = getApiBaseUrl();
  const url = absoluteUrl
    ? path
    : `${base}${path.startsWith("/") ? path : `/${path}`}`;
  const headers = new Headers(fetchOptions.headers);
  if (!headers.has("Content-Type") && fetchOptions.body) {
    headers.set("Content-Type", "application/json");
  }
  applyAuthHeader(headers);

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
  if (wakeInFlight) return wakeInFlight;

  wakeInFlight = (async () => {
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
  })();

  try {
    await wakeInFlight;
  } finally {
    wakeInFlight = null;
  }
}

/**
 * After login, Summary and StarredSymbols used to race: heavy /overview in
 * parallel with /portfolio. Overview often aborted mid-Yahoo while Retries
 * kept failing until the Portfolio tab ran a cheap authenticated read first.
 * Coalesce wake + /portfolio so that warm path always precedes /overview.
 */
export async function ensureSessionReady(): Promise<void> {
  await wakeApi();
  try {
    await fetchPortfolioShared();
  } catch {
    // Warm failed — caller still attempts its own endpoint.
  }
}

async function fetchPortfolioShared(): Promise<PortfolioPayload> {
  const now = Date.now();
  if (portfolioWarm && now - portfolioWarm.at < PORTFOLIO_WARM_TTL_MS) {
    return portfolioWarm.promise;
  }
  const promise = apiFetch<PortfolioPayload>("/portfolio");
  portfolioWarm = { at: now, promise };
  try {
    return await promise;
  } catch (err) {
    if (portfolioWarm?.promise === promise) portfolioWarm = null;
    throw err;
  }
}

export async function fetchConfig(): Promise<ApiConfig> {
  return apiFetch<ApiConfig>("/config");
}

export const api = {
  wake: wakeApi,
  ensureSessionReady,
  config: fetchConfig,
  me: () =>
    apiFetch<{
      authEnabled: boolean;
      user: {
        id: number;
        email?: string | null;
        name?: string | null;
        picture?: string | null;
        plan?: string | null;
      } | null;
      planLimits?: unknown;
    }>("/me"),
  exchangeGoogleIdToken: (idToken: string) =>
    apiFetch<{
      accessToken: string;
      tokenType: string;
      user: {
        id: number;
        email?: string | null;
        name?: string | null;
        picture?: string | null;
        plan?: string | null;
      };
    }>(`${getApiOrigin()}/auth/mobile/google`, {
      method: "POST",
      body: JSON.stringify({ idToken }),
      absoluteUrl: true,
    }),
  mobileLogout: () =>
    apiFetch<{ status: string }>(`${getApiOrigin()}/auth/mobile/logout`, {
      method: "POST",
      absoluteUrl: true,
    }),
  overview: () =>
    apiFetch<import("./types").Overview>("/overview", { timeoutMs: OVERVIEW_TIMEOUT_MS }),
  portfolio: () => fetchPortfolioShared(),
  holdings: () => apiFetch<{ holdings: import("./types").Holding[] }>("/holdings"),
  updateHolding: (
    symbol: string,
    data: {
      quantity?: number | null;
      costBasis?: number | null;
      purchaseDate?: string | null;
    },
  ) =>
    apiFetch<import("./types").Holding | { status: string; symbol: string }>(
      `/holdings/${encodeURIComponent(symbol)}`,
      {
        method: "PUT",
        body: JSON.stringify(data),
      },
    ),
  deleteHolding: (symbol: string) =>
    apiFetch<{ status?: string; symbol?: string }>(`/holdings/${encodeURIComponent(symbol)}`, {
      method: "DELETE",
    }),
  searchSymbols: (q: string, limit = 12) =>
    apiFetch<{
      query: string;
      results: import("./types").TickerSearchHit[];
      providerUnavailable?: boolean;
      error?: string;
    }>(`/symbols/search?q=${encodeURIComponent(q)}&limit=${limit}`),
  addSymbol: (symbol: string) =>
    apiFetch<import("./types").PortfolioSymbol>("/symbols", {
      method: "POST",
      body: JSON.stringify({ symbol }),
    }),
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
  syncStarredSymbols: (symbols: string[]) =>
    apiFetch<{ symbols: string[] }>("/starred-symbols", {
      method: "PUT",
      body: JSON.stringify({ symbols }),
    }),
  addNote: (symbol: string, data: import("./types").Note) =>
    apiFetch<import("./types").Note>(`/symbols/${encodeURIComponent(symbol)}/notes`, {
      method: "POST",
      body: JSON.stringify(data),
      timeoutMs: NOTE_SAVE_TIMEOUT_MS,
    }),
  updateNote: (symbol: string, noteId: number, data: import("./types").Note) =>
    apiFetch<import("./types").Note>(
      `/symbols/${encodeURIComponent(symbol)}/notes/${noteId}`,
      {
        method: "PUT",
        body: JSON.stringify(data),
        timeoutMs: NOTE_SAVE_TIMEOUT_MS,
      },
    ),
  deleteNote: (symbol: string, noteId: number) =>
    apiFetch<{ status: string; id: number }>(
      `/symbols/${encodeURIComponent(symbol)}/notes/${noteId}`,
      { method: "DELETE" },
    ),
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
  preferences: () =>
    apiFetch<{
      portfolioFit?: Record<string, unknown>;
      taxTrim?: {
        pricingMode?: import("./types").TaxTrimPricingMode;
        lossScoreThreshold?: number;
        trimScoreThreshold?: number;
        matchLossPool?: boolean;
      };
    }>("/preferences"),
  updatePreferences: (payload: {
    portfolioFit?: Record<string, unknown>;
    taxTrim?: {
      pricingMode?: import("./types").TaxTrimPricingMode;
      lossScoreThreshold?: number;
      trimScoreThreshold?: number;
      matchLossPool?: boolean;
    };
  }) =>
    apiFetch<{
      portfolioFit?: Record<string, unknown>;
      taxTrim?: {
        pricingMode?: import("./types").TaxTrimPricingMode;
        lossScoreThreshold?: number;
        trimScoreThreshold?: number;
        matchLossPool?: boolean;
      };
    }>("/preferences", {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),
  taxTrimProposal: (params: {
    pricingMode?: import("./types").TaxTrimPricingMode;
    lossScoreThreshold?: number;
    trimScoreThreshold?: number;
    matchLossPool?: boolean;
    selectedSymbols?: string[];
  }) =>
    apiFetch<import("./types").TaxTrimProposal>("/tax-trim/proposal", {
      method: "POST",
      body: JSON.stringify(params),
    }),
  taxTrimOrderBook: (params: {
    pricingMode?: import("./types").TaxTrimPricingMode;
    lossScoreThreshold?: number;
    trimScoreThreshold?: number;
    matchLossPool?: boolean;
    selectedSymbols?: string[];
  }) =>
    apiFetch<import("./types").TaxTrimOrderBook>("/tax-trim/order-book", {
      method: "POST",
      body: JSON.stringify(params),
    }),
};

export function showApiHostInDev(): boolean {
  return (
    process.env.EXPO_PUBLIC_SHOW_API_HOST === "1" ||
    Constants.expoConfig?.extra?.showApiHost === true
  );
}
