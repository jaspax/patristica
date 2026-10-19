// Client-side search, filtering and sorting of the work index.

import { languageInfo } from "./lang";
import { workAuthors, type AuthorMap, type LibraryIndex, type WorkRow } from "./library";
import { currentAuthorId, currentSourceId } from "./redirects";

/** Lowercase and strip diacritics, so "Ἰωάννης" matches "ιωαννης" and "Basilius" matches "BASÍLIUS". */
export function fold(text: string): string {
  return text.normalize("NFD").replace(/\p{M}/gu, "").toLowerCase();
}

export type SortKey = "author" | "title" | "language" | "date" | "source" | "chunks";
export const SORT_KEYS: SortKey[] = ["author", "title", "language", "date", "source", "chunks"];

/**
 * Value of the author facet for works with no author (`author_ids: []`).
 * Author ids are slugs of a person's name, and no author is called this.
 */
export const ANONYMOUS = "anonymous";

/** Facets that take several values; none selected means all. */
export const MULTI_KEYS = ["author", "language", "genre"] as const;

export interface ViewState {
  q: string;
  /** Author ids and/or ANONYMOUS; a work by any of them matches. */
  author: string[];
  /** Language codes; a work in any of them matches. */
  language: string[];
  genre: string[];
  source: string;
  from: number | null;
  to: number | null;
  sort: SortKey;
  dir: "asc" | "desc";
}

export const DEFAULT_VIEW: ViewState = {
  q: "",
  author: [],
  language: [],
  genre: [],
  source: "",
  from: null,
  to: null,
  sort: "author",
  dir: "asc",
};

const NO_AUTHORS: AuthorMap = new Map();

function parseYear(value: string | null): number | null {
  if (value === null || value.trim() === "") return null;
  const n = Number(value);
  return Number.isInteger(n) ? n : null;
}

/**
 * Values of a multi-valued facet: repeated parameters (`?language=grc&language=lat`,
 * as written by viewStateToParams), also accepting comma-separated values, as the API does.
 */
function parseList(params: URLSearchParams, key: string): string[] {
  const values = params.getAll(key).flatMap((v) => v.split(","));
  return [...new Set(values.map((v) => v.trim()).filter(Boolean))];
}

/** Read the view state from URL query parameters; invalid values fall back to defaults. */
export function parseViewState(params: URLSearchParams): ViewState {
  const sort = params.get("sort") as SortKey | null;
  return {
    q: params.get("q") ?? "",
    // A renamed author's old id still selects the author.
    author: [...new Set(parseList(params, "author").map((id) => currentAuthorId(id)))],
    language: parseList(params, "language"),
    genre: parseList(params, "genre"),
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
    if (Array.isArray(value)) {
      for (const v of value) params.append(key, v);
    } else if (value !== DEFAULT_VIEW[key] && value !== null && value !== "") {
      params.set(key, String(value));
    }
  }
  return params;
}

/** Library index URL listing the works of one author (or ANONYMOUS). */
export function authorFilterHref(authorId: string): string {
  return `/works?${viewStateToParams({ ...DEFAULT_VIEW, author: [authorId] })}`;
}

// Haystacks depend on the author index too, so they are cached per author map.
const haystacks = new WeakMap<AuthorMap, WeakMap<WorkRow, string>>();

function haystack(row: WorkRow, sources: Record<string, string>, authors: AuthorMap): string {
  let cache = haystacks.get(authors);
  if (cache === undefined) {
    cache = new WeakMap();
    haystacks.set(authors, cache);
  }
  let h = cache.get(row);
  if (h === undefined) {
    const names = row.author_ids.flatMap((id) => {
      const a = authors.get(id);
      return a ? [a.name, ...a.aliases] : [];
    });
    h = fold(
      [row.author ?? "", ...names, row.title, row.edition ?? "", sources[row.source_id] ?? "", row.id].join(" "),
    );
    cache.set(row, h);
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

/** Whether the work is by any of `authors` (ids, or ANONYMOUS for works with no author); none means all. */
function byAuthor(row: WorkRow, authors: string[]): boolean {
  if (authors.length === 0) return true;
  return authors.some((a) => (a === ANONYMOUS ? row.author_ids.length === 0 : row.author_ids.includes(a)));
}

/** Whether `value` is one of `selected`; none selected means all. */
function oneOf(selected: string[], value: string): boolean {
  return selected.length === 0 || selected.includes(value);
}

/**
 * Filter works by the view state. The text query matches the source's author
 * string, the authors' names and aliases (so "Hieronymus" finds Jerome),
 * title, edition, collection and id; every whitespace-separated term must match.
 */
export function filterWorks(
  rows: WorkRow[],
  state: ViewState,
  sources: Record<string, string>,
  authors: AuthorMap = NO_AUTHORS,
): WorkRow[] {
  const terms = fold(state.q).split(/\s+/).filter(Boolean);
  return rows.filter(
    (row) =>
      byAuthor(row, state.author) &&
      oneOf(state.language, row.language) &&
      oneOf(state.genre, row.genre) &&
      (!state.source || row.source_id === state.source) &&
      inDateRange(row, state.from, state.to) &&
      terms.every((t) => haystack(row, sources, authors).includes(t)),
  );
}

export interface AuthorFacetValue {
  /** Author id, or ANONYMOUS. */
  id: string;
  name: string;
  /** Works by the author; a work with several authors counts under each. */
  count: number;
}

const collator = new Intl.Collator(undefined, { sensitivity: "base", numeric: true });

/** Number of works per author id; a work with several authors counts under each. */
export function workCounts(rows: WorkRow[]): Map<string, number> {
  const counts = new Map<string, number>();
  for (const row of rows) {
    for (const id of new Set(row.author_ids)) counts.set(id, (counts.get(id) ?? 0) + 1);
  }
  return counts;
}

/**
 * Values of the author facet: "Anonymous" first (when any work has no
 * author), then every author with at least one work, by name.
 */
export function authorFacet(rows: WorkRow[], authors: AuthorMap): AuthorFacetValue[] {
  const counts = workCounts(rows);
  const anonymous = rows.filter((row) => row.author_ids.length === 0).length;
  const values = [...counts].map(([id, count]) => ({ id, name: authors.get(id)?.name ?? id, count }));
  values.sort((a, b) => collator.compare(a.name, b.name) || collator.compare(a.id, b.id));
  return anonymous > 0 ? [{ id: ANONYMOUS, name: "Anonymous", count: anonymous }, ...values] : values;
}

/** The values offered by each facet of the filter form (FilterFields). */
export interface Facets {
  /** Language codes, by language name. */
  languages: string[];
  genres: string[];
  /** [source_id, label], by label. */
  sources: [string, string][];
  authors: AuthorFacetValue[];
}

/** Facet values present in the library index. */
export function libraryFacets(index: LibraryIndex, authors: AuthorMap): Facets {
  const present = (key: "language" | "genre") => [...new Set(index.works.map((w) => w[key]))];
  return {
    languages: present("language").sort((a, b) =>
      languageInfo(a).name.localeCompare(languageInfo(b).name),
    ),
    genres: present("genre").sort(),
    sources: Object.entries(index.sources).sort((a, b) => a[1].localeCompare(b[1])),
    authors: authorFacet(index.works, authors),
  };
}

function sortValue(
  row: WorkRow,
  key: SortKey,
  sources: Record<string, string>,
  authors: AuthorMap,
): string | number | null {
  switch (key) {
    case "author":
      return workAuthors(row, authors)
        .map((a) => a.name)
        .join("; ");
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
 * Sort works by `key`. Missing values (anonymous, undated) always sort last,
 * in either direction; ties are broken by title, then id. Authors sort by
 * display name.
 */
export function sortWorks(
  rows: WorkRow[],
  key: SortKey,
  dir: "asc" | "desc",
  sources: Record<string, string>,
  authors: AuthorMap = NO_AUTHORS,
): WorkRow[] {
  const sign = dir === "asc" ? 1 : -1;
  return [...rows].sort((a, b) => {
    const va = sortValue(a, key, sources, authors);
    const vb = sortValue(b, key, sources, authors);
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
