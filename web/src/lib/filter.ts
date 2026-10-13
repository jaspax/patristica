// Client-side search, filtering and sorting of the work index.

import type { WorkRow } from "./library";
import { currentSourceId } from "./redirects";

/** Lowercase and strip diacritics, so "Ἰωάννης" matches "ιωαννης" and "Basilius" matches "BASÍLIUS". */
export function fold(text: string): string {
  return text.normalize("NFD").replace(/\p{M}/gu, "").toLowerCase();
}

export type SortKey = "author" | "title" | "language" | "date" | "source" | "chunks";
export const SORT_KEYS: SortKey[] = ["author", "title", "language", "date", "source", "chunks"];

export interface ViewState {
  q: string;
  language: string;
  genre: string;
  source: string;
  from: number | null;
  to: number | null;
  sort: SortKey;
  dir: "asc" | "desc";
}

export const DEFAULT_VIEW: ViewState = {
  q: "",
  language: "",
  genre: "",
  source: "",
  from: null,
  to: null,
  sort: "author",
  dir: "asc",
};

function parseYear(value: string | null): number | null {
  if (value === null || value.trim() === "") return null;
  const n = Number(value);
  return Number.isInteger(n) ? n : null;
}

/** Read the view state from URL query parameters; invalid values fall back to defaults. */
export function parseViewState(params: URLSearchParams): ViewState {
  const sort = params.get("sort") as SortKey | null;
  return {
    q: params.get("q") ?? "",
    language: params.get("language") ?? "",
    genre: params.get("genre") ?? "",
    // Old links may name a source by its pre-#102 id (`scripture/kjv`).
    source: currentSourceId(params.get("source") ?? ""),
    from: parseYear(params.get("from")),
    to: parseYear(params.get("to")),
    sort: sort && SORT_KEYS.includes(sort) ? sort : DEFAULT_VIEW.sort,
    dir: params.get("dir") === "desc" ? "desc" : "asc",
  };
}

/** Serialize the view state, omitting default values. */
export function viewStateToParams(state: ViewState): URLSearchParams {
  const params = new URLSearchParams();
  for (const key of Object.keys(DEFAULT_VIEW) as (keyof ViewState)[]) {
    const value = state[key];
    if (value !== DEFAULT_VIEW[key] && value !== null && value !== "") {
      params.set(key, String(value));
    }
  }
  return params;
}

const haystacks = new WeakMap<WorkRow, string>();

function haystack(row: WorkRow, sources: Record<string, string>): string {
  let h = haystacks.get(row);
  if (h === undefined) {
    h = fold([row.author ?? "", row.title, row.edition ?? "", sources[row.source_id] ?? "", row.id].join(" "));
    haystacks.set(row, h);
  }
  return h;
}

/** Whether the work's date (or date range) overlaps [from, to]. Undated works never match a date filter. */
function inDateRange(row: WorkRow, from: number | null, to: number | null): boolean {
  if (from === null && to === null) return true;
  const [lo, hi] = row.date_range ?? (row.date !== null ? [row.date, row.date] : [null, null]);
  if (lo === null || hi === null) return false;
  return (from === null || hi >= from) && (to === null || lo <= to);
}

/**
 * Filter works by the view state. The text query matches author, title,
 * edition, collection and id; every whitespace-separated term must match.
 */
export function filterWorks(
  rows: WorkRow[],
  state: ViewState,
  sources: Record<string, string>,
): WorkRow[] {
  const terms = fold(state.q).split(/\s+/).filter(Boolean);
  return rows.filter(
    (row) =>
      (!state.language || row.language === state.language) &&
      (!state.genre || row.genre === state.genre) &&
      (!state.source || row.source_id === state.source) &&
      inDateRange(row, state.from, state.to) &&
      terms.every((t) => haystack(row, sources).includes(t)),
  );
}

const collator = new Intl.Collator(undefined, { sensitivity: "base", numeric: true });

function sortValue(row: WorkRow, key: SortKey, sources: Record<string, string>): string | number | null {
  switch (key) {
    case "author":
      return row.author;
    case "title":
      return row.title;
    case "language":
      return row.language;
    case "date":
      return row.date;
    case "source":
      return sources[row.source_id] ?? row.source_id;
    case "chunks":
      return row.chunks;
  }
}

/**
 * Sort works by `key`. Missing values (no author, undated) always sort last,
 * in either direction; ties are broken by title, then id.
 */
export function sortWorks(
  rows: WorkRow[],
  key: SortKey,
  dir: "asc" | "desc",
  sources: Record<string, string>,
): WorkRow[] {
  const sign = dir === "asc" ? 1 : -1;
  return [...rows].sort((a, b) => {
    const va = sortValue(a, key, sources);
    const vb = sortValue(b, key, sources);
    const aMissing = va === null || va === "";
    const bMissing = vb === null || vb === "";
    if (aMissing !== bMissing) return aMissing ? 1 : -1;
    if (!aMissing && !bMissing) {
      const c =
        typeof va === "number" && typeof vb === "number"
          ? va - vb
          : collator.compare(String(va), String(vb));
      if (c !== 0) return sign * c;
    }
    return collator.compare(a.title, b.title) || collator.compare(a.id, b.id);
  });
}
