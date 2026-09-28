"use client";

import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import type { KeyboardEvent, ReactNode } from "react";
import { OPEN_ON_FOCUS, fetchSuggestions, filterOptions } from "../lib/suggest";
import type { SuggestKind, Suggestion } from "../lib/suggest";

export type SuggestSource = SuggestKind | Suggestion[] | string[];

const DEBOUNCE_MS = 150;
const DEFAULT_LIMIT = 8;

function toOptions(source: Suggestion[] | string[]): Suggestion[] {
  return source.map((o) => (typeof o === "string" ? { value: o, label: o } : o));
}

/**
 * Suggestion state and keyboard handling for a text input.
 *
 * Shared by TagInput (many values) and SuggestInput (one value) so both
 * behave identically: debounced fetch, aborted stale requests, arrow keys,
 * Enter to pick, Escape to close.
 */
export function useSuggest({
  source,
  query,
  exclude = [],
  limit = DEFAULT_LIMIT,
  onPick,
}: {
  source?: SuggestSource;
  query: string;
  exclude?: string[];
  limit?: number;
  onPick: (s: Suggestion) => void;
}) {
  const listId = useId();
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<Suggestion[]>([]);
  const [active, setActive] = useState(-1);
  const [loading, setLoading] = useState(false);
  const excludeKey = exclude.map((e) => e.toLowerCase()).join("\u0001");

  const staticOptions = useMemo(
    () => (Array.isArray(source) ? toOptions(source) : null),
    [source],
  );
  const kind = typeof source === "string" ? source : null;
  const openOnFocus = Boolean(staticOptions) || (kind !== null && OPEN_ON_FOCUS.has(kind));

  useEffect(() => {
    if (!source || !open) return;
    const q = query.trim();
    const excluded = new Set(excludeKey ? excludeKey.split("\u0001") : []);
    const keep = (list: Suggestion[]) =>
      list.filter((s) => !excluded.has(s.value.toLowerCase()) && !excluded.has(s.label.toLowerCase())).slice(0, limit);

    if (staticOptions) {
      setItems(keep(filterOptions(staticOptions, q, limit + excluded.size)));
      setActive(-1);
      return;
    }
    if (!q && !openOnFocus) {
      setItems([]);
      return;
    }
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      setLoading(true);
      // Ask for a few extra so hiding already-chosen values still fills the list.
      fetchSuggestions(kind as SuggestKind, q, Math.min(25, limit + excluded.size), controller.signal)
        .then((list) => {
          setItems(keep(list));
          setActive(-1);
        })
        .catch(() => {
          /* aborted or offline: keep the last list; typing still works */
        })
        .finally(() => {
          if (!controller.signal.aborted) setLoading(false);
        });
    }, q ? DEBOUNCE_MS : 0);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [source, kind, staticOptions, query, open, openOnFocus, excludeKey, limit]);

  const visible = open && items.length > 0;

  const pick = useCallback(
    (s: Suggestion) => {
      onPick(s);
      setItems([]);
      setActive(-1);
    },
    [onPick],
  );

  /**
   * Returns the suggestion Enter should commit: the highlighted one, or one
   * that exactly matches what was typed (so "reactjs" becomes "React").
   */
  const resolveEnter = useCallback((): Suggestion | null => {
    if (visible && active >= 0 && items[active]) return items[active];
    const typed = query.trim().toLowerCase();
    if (!typed) return null;
    return items.find((s) => s.exact || s.label.toLowerCase() === typed || s.value.toLowerCase() === typed) ?? null;
  }, [visible, active, items, query]);

  /** Handles navigation keys. Returns true when the key was consumed. */
  const onKeyDown = useCallback(
    (event: KeyboardEvent<HTMLInputElement>): boolean => {
      if (!source) return false;
      if (event.key === "ArrowDown") {
        event.preventDefault();
        if (!open) setOpen(true);
        setActive((i) => (items.length ? (i + 1) % items.length : -1));
        return true;
      }
      if (event.key === "ArrowUp") {
        event.preventDefault();
        setActive((i) => (items.length ? (i <= 0 ? items.length - 1 : i - 1) : -1));
        return true;
      }
      if (event.key === "Escape" && visible) {
        event.preventDefault();
        setOpen(false);
        return true;
      }
      if (event.key === "Tab" && visible && active >= 0 && items[active]) {
        event.preventDefault();
        pick(items[active]);
        return true;
      }
      return false;
    },
    [source, open, items, visible, active, pick],
  );

  const inputProps = source
    ? {
        role: "combobox" as const,
        "aria-autocomplete": "list" as const,
        "aria-expanded": visible,
        "aria-controls": listId,
        "aria-activedescendant": visible && active >= 0 ? `${listId}-${active}` : undefined,
        autoComplete: "off",
        onFocus: () => setOpen(true),
      }
    : {};

  return {
    listId,
    items,
    active,
    setActive,
    visible,
    loading,
    open,
    setOpen,
    pick,
    resolveEnter,
    onKeyDown,
    inputProps,
  };
}

/** Wraps the part of the label that matches the query in <mark>. */
function highlight(label: string, query: string): ReactNode {
  const q = query.trim().toLowerCase();
  if (!q) return label;
  const lower = label.toLowerCase();
  let index = lower.indexOf(q);
  let length = q.length;
  if (index < 0) {
    // Highlight the first word that starts with the first query word.
    const first = q.split(/\s+/)[0];
    const match = new RegExp(`(^|[\\s/(-])(${first.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")})`, "i").exec(label);
    if (!match) return label;
    index = match.index + match[1].length;
    length = first.length;
  }
  return (
    <>
      {label.slice(0, index)}
      <mark>{label.slice(index, index + length)}</mark>
      {label.slice(index + length)}
    </>
  );
}

export function SuggestList({
  id,
  items,
  active,
  query,
  visible,
  onPick,
  onHover,
}: {
  id: string;
  items: Suggestion[];
  active: number;
  query: string;
  visible: boolean;
  onPick: (s: Suggestion) => void;
  onHover: (index: number) => void;
}) {
  const listRef = useRef<HTMLUListElement>(null);

  useEffect(() => {
    if (active < 0 || !listRef.current) return;
    const el = listRef.current.children[active] as HTMLElement | undefined;
    el?.scrollIntoView({ block: "nearest" });
  }, [active]);

  if (!visible) return null;
  return (
    <ul className="suggest-list" id={id} role="listbox" ref={listRef}>
      {items.map((item, index) => (
        <li
          key={`${item.value}-${index}`}
          id={`${id}-${index}`}
          role="option"
          aria-selected={index === active}
          className={`suggest-option ${index === active ? "is-active" : ""}`.trim()}
          // mousedown, not click: picking must happen before the input blurs.
          onMouseDown={(event) => {
            event.preventDefault();
            onPick(item);
          }}
          onMouseEnter={() => onHover(index)}
        >
          <span className="suggest-label">{highlight(item.label, query)}</span>
          {(item.hint || item.source === "yours") && (
            <span className={`suggest-hint ${item.source === "yours" ? "is-yours" : ""}`.trim()}>
              {item.hint || "Yours"}
            </span>
          )}
        </li>
      ))}
    </ul>
  );
}
