/**
 * Type-ahead suggestion client.
 *
 * Keeps request volume low: callers debounce, stale requests are aborted, and
 * identical (kind, query) lookups are served from a small LRU cache or share
 * one in-flight request.
 */
import { api } from "./api";

export type SuggestKind =
  | "location"
  | "role"
  | "skill"
  | "title_word"
  | "company"
  | "industry"
  | "employment_type"
  | "company_type"
  | "keyword"
  | "query";

export interface Suggestion {
  value: string;
  label: string;
  hint?: string;
  source?: "catalog" | "yours";
  /** The query equals this entry or one of its aliases ("reactjs" -> React). */
  exact?: boolean;
}

interface SuggestResponse {
  kind: string;
  q: string;
  items: Suggestion[];
}

const CACHE_LIMIT = 300;
const CACHE_TTL_MS = 60_000;
const cache = new Map<string, { at: number; items: Suggestion[] }>();
const inflight = new Map<string, Promise<Suggestion[]>>();

/** Kinds with a short, closed list: show options as soon as the field is focused. */
export const OPEN_ON_FOCUS: ReadonlySet<SuggestKind> = new Set(["employment_type", "company_type"]);

function remember(key: string, items: Suggestion[]): void {
  cache.delete(key);
  cache.set(key, { at: Date.now(), items });
  if (cache.size > CACHE_LIMIT) {
    const oldest = cache.keys().next().value;
    if (oldest !== undefined) cache.delete(oldest);
  }
}

export function fetchSuggestions(
  kind: SuggestKind,
  q: string,
  limit: number,
  signal?: AbortSignal,
): Promise<Suggestion[]> {
  const query = q.trim().toLowerCase();
  const key = `${kind}|${limit}|${query}`;
  const hit = cache.get(key);
  if (hit && Date.now() - hit.at < CACHE_TTL_MS) return Promise.resolve(hit.items);

  let pending = inflight.get(key);
  if (!pending) {
    pending = api
      .get<SuggestResponse>("/api/v1/suggest", { kind, q: query, limit })
      .then((res) => {
        remember(key, res.items);
        return res.items;
      })
      .finally(() => inflight.delete(key));
    inflight.set(key, pending);
  }
  if (!signal) return pending;
  // The shared request keeps running for other callers; this caller just
  // stops waiting when its signal aborts.
  return new Promise<Suggestion[]>((resolve, reject) => {
    const onAbort = () => reject(new DOMException("Aborted", "AbortError"));
    if (signal.aborted) return onAbort();
    signal.addEventListener("abort", onAbort, { once: true });
    pending!.then(
      (items) => {
        signal.removeEventListener("abort", onAbort);
        resolve(items);
      },
      (err) => {
        signal.removeEventListener("abort", onAbort);
        reject(err);
      },
    );
  });
}

/** Drop cached results, e.g. after the user saves new roles or skills. */
export function clearSuggestionCache(): void {
  cache.clear();
}

/** Local filtering for fields given a fixed option list instead of a kind. */
export function filterOptions(options: Suggestion[], q: string, limit: number): Suggestion[] {
  const query = q.trim().toLowerCase();
  if (!query) return options.slice(0, limit);
  const words = query.split(/\s+/);
  const scored: Array<[number, Suggestion]> = [];
  for (const option of options) {
    const label = option.label.toLowerCase();
    let score = -1;
    if (label === query) score = 3;
    else if (label.startsWith(query)) score = 2;
    else if (words.every((w) => label.split(/\s+/).some((lw) => lw.startsWith(w)))) score = 1;
    else if (label.includes(query)) score = 0;
    if (score >= 0) scored.push([score, option]);
  }
  scored.sort((a, b) => b[0] - a[0]);
  return scored.slice(0, limit).map(([, option]) => option);
}
