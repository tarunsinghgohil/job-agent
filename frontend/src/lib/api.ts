/**
 * Typed fetch client for the v1 API.
 *
 * The access token lives in module memory only. The durable half of the
 * session is the httpOnly `refresh_token` cookie, which is why every request
 * sends `credentials: "include"` and why a 401 is recoverable without any
 * browser storage.
 */
import type { ApiErrorBody, JsonObject } from "./types";

export const API_BASE = (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").replace(
  /\/+$/,
  "",
);

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details?: JsonObject;

  constructor(status: number, code: string, message: string, details?: JsonObject) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

/* ------------------------------------------------------------ token store */

let accessToken: string | null = null;
let onUnauthenticated: (() => void) | null = null;

export function setAccessToken(token: string | null): void {
  accessToken = token;
}

export function getAccessToken(): string | null {
  return accessToken;
}

/** Registered by the auth provider so the client can hard-logout on failure. */
export function setUnauthenticatedHandler(handler: (() => void) | null): void {
  onUnauthenticated = handler;
}

/* ---------------------------------------------------------------- helpers */

export type QueryValue = string | number | boolean | null | undefined;

export function buildQuery(params: Record<string, QueryValue>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === "") continue;
    search.set(key, String(value));
  }
  const s = search.toString();
  return s ? `?${s}` : "";
}

function isApiErrorBody(value: unknown): value is ApiErrorBody {
  if (typeof value !== "object" || value === null) return false;
  const err = (value as { error?: unknown }).error;
  return typeof err === "object" && err !== null && "message" in (err as object);
}

async function toApiError(response: Response): Promise<ApiError> {
  let parsed: unknown = null;
  try {
    parsed = await response.json();
  } catch {
    // Non-JSON error bodies (proxy pages, network appliances) are still errors.
  }
  if (isApiErrorBody(parsed)) {
    return new ApiError(
      response.status,
      parsed.error.code || `http_${response.status}`,
      parsed.error.message || response.statusText,
      parsed.error.details,
    );
  }
  return new ApiError(
    response.status,
    `http_${response.status}`,
    response.statusText || `Request failed with status ${response.status}`,
  );
}

/* ---------------------------------------------------------------- refresh */

// One shared promise so N concurrent 401s trigger exactly one refresh call.
let refreshInFlight: Promise<string | null> | null = null;

async function performRefresh(): Promise<string | null> {
  try {
    const response = await fetch(`${API_BASE}/api/v1/auth/refresh`, {
      method: "POST",
      credentials: "include",
      headers: { Accept: "application/json" },
    });
    if (!response.ok) return null;
    const data = (await response.json()) as { access_token?: string };
    if (!data.access_token) return null;
    accessToken = data.access_token;
    return data.access_token;
  } catch {
    return null;
  }
}

export function refreshAccessToken(): Promise<string | null> {
  if (!refreshInFlight) {
    refreshInFlight = performRefresh().finally(() => {
      refreshInFlight = null;
    });
  }
  return refreshInFlight;
}

function failAuth(): void {
  accessToken = null;
  if (onUnauthenticated) {
    onUnauthenticated();
  } else if (typeof window !== "undefined" && window.location.pathname !== "/login") {
    window.location.assign("/login");
  }
}

/* ------------------------------------------------------------ core request */

export interface RequestOptions {
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  body?: unknown;
  /** FormData bypasses JSON encoding; the browser sets the boundary header. */
  form?: FormData;
  query?: Record<string, QueryValue>;
  signal?: AbortSignal;
  /** Set for endpoints that must never trigger the refresh dance. */
  skipAuthRetry?: boolean;
}

async function rawFetch(path: string, options: RequestOptions): Promise<Response> {
  const headers: Record<string, string> = { Accept: "application/json" };
  if (accessToken) headers.Authorization = `Bearer ${accessToken}`;

  let body: BodyInit | undefined;
  if (options.form) {
    body = options.form;
  } else if (options.body !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(options.body);
  }

  return fetch(`${API_BASE}${path}${buildQuery(options.query ?? {})}`, {
    method: options.method ?? "GET",
    credentials: "include",
    headers,
    body,
    signal: options.signal,
    cache: "no-store",
  });
}

/** Returns the raw Response, refreshing once on 401. Used for downloads too. */
export async function apiFetch(path: string, options: RequestOptions = {}): Promise<Response> {
  let response: Response;
  try {
    response = await rawFetch(path, options);
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new ApiError(0, "network_error", "Could not reach the API. Is the backend running?");
  }

  if (response.status !== 401 || options.skipAuthRetry) return response;

  const token = await refreshAccessToken();
  if (!token) {
    failAuth();
    throw new ApiError(401, "unauthenticated", "Your session expired. Please sign in again.");
  }

  try {
    response = await rawFetch(path, options);
  } catch {
    throw new ApiError(0, "network_error", "Could not reach the API. Is the backend running?");
  }
  if (response.status === 401) {
    failAuth();
    throw new ApiError(401, "unauthenticated", "Your session expired. Please sign in again.");
  }
  return response;
}

export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const response = await apiFetch(path, options);
  if (!response.ok) throw await toApiError(response);
  if (response.status === 204) return undefined as T;
  const text = await response.text();
  if (!text) return undefined as T;
  return JSON.parse(text) as T;
}

export const api = {
  get: <T>(path: string, query?: Record<string, QueryValue>, signal?: AbortSignal) =>
    request<T>(path, { method: "GET", query, signal }),
  post: <T>(path: string, body?: unknown, query?: Record<string, QueryValue>) =>
    request<T>(path, { method: "POST", body, query }),
  put: <T>(path: string, body?: unknown) => request<T>(path, { method: "PUT", body }),
  patch: <T>(path: string, body?: unknown) => request<T>(path, { method: "PATCH", body }),
  del: <T>(path: string, body?: unknown) => request<T>(path, { method: "DELETE", body }),
  upload: <T>(path: string, form: FormData) => request<T>(path, { method: "POST", form }),
};

/**
 * Downloads a protected file. A plain <a href> cannot carry the bearer token,
 * so the bytes are fetched and handed to a temporary object URL instead.
 */
export async function downloadFile(path: string, fallbackName: string): Promise<void> {
  const response = await apiFetch(path);
  if (!response.ok) throw await toApiError(response);

  const disposition = response.headers.get("Content-Disposition") ?? "";
  const match = /filename\*?=(?:UTF-8'')?"?([^";]+)"?/i.exec(disposition);
  const filename = match ? decodeURIComponent(match[1]) : fallbackName;

  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error) return error.message;
  return "Something went wrong.";
}
