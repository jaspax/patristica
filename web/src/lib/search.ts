// Passage search through the search API (`GET /api/search`, api/search.py, #141).

import { API_URL } from "./config";
import { DEFAULT_VIEW, parseViewState, viewStateToParams } from "./filter";
import { formatYear } from "./format";
import { workHref } from "./library";

/** The search page's URL state: the query and the library index's facets. */
export interface SearchState {
  q: string;
  author: string;
  language: string;
  genre: string;
  source: string;
  from: number | null;
  to: number | null;
}

export const DEFAULT_SEARCH: SearchState = {
  q: "",
  author: "",
  language: "",
  genre: "",
  source: "",
  from: null,
  to: null,
};

/** Results per request. */
export const PAGE_SIZE = 20;
/** Give up on a request after this long (the API's own Voyage timeout is 5 s). */
export const TIMEOUT_MS = 20_000;

/** Read the search state from the URL query, with the library index's rules for each facet. */
export function parseSearchState(params: URLSearchParams): SearchState {
  const { q, author, language, genre, source, from, to } = parseViewState(params);
  return { q, author, language, genre, source, from, to };
}

/** Serialize the search state, omitting defaults: `/search?{this}` is a shareable search. */
export function searchStateToParams(state: SearchState): URLSearchParams {
  return viewStateToParams({ ...DEFAULT_VIEW, ...state });
}

export function searchHref(state: Partial<SearchState>): string {
  const query = searchStateToParams({ ...DEFAULT_SEARCH, ...state }).toString();
  return query ? `/search?${query}` : "/search";
}

/** The API request for one page of results. */
export function searchApiUrl(state: SearchState, offset = 0, limit = PAGE_SIZE): string {
  const params = new URLSearchParams({ q: state.q.trim() });
  for (const key of ["author", "language", "genre", "source"] as const) {
    if (state[key]) params.set(key, state[key]);
  }
  if (state.from !== null) params.set("date_from", String(state.from));
  if (state.to !== null) params.set("date_to", String(state.to));
  params.set("limit", String(limit));
  if (offset) params.set("offset", String(offset));
  return `${API_URL}/search?${params}`;
}

export interface SearchResult {
  chunk_id: string;
  work_id: string;
  canonical_ref: string;
  language: string;
  text: string;
  text_truncated: boolean;
  translation: { language: string; text: string; model: string; machine: boolean } | null;
  score: number;
  /** Which vector matched: the original text or its English translation. */
  matched: "text" | "translation";
  date_composed: number | null;
  date_range: [number, number] | null;
  out_of_period: boolean;
  /** `{author}, *{title}* {ref}` (IMPLEMENTATION_PLAN.md §3.2). */
  citation: string;
  work: {
    title: string;
    authors: { id: string; name: string }[];
    genre: string;
    tradition: string | null;
    date_composed: number | null;
    date_range: [number, number] | null;
    edition: string | null;
    source_label: string;
    license: string;
    provenance_url: string | null;
  };
}

export interface SearchResponse {
  query: string;
  /** How the query was run; "phrase" queries run as "vector" until #86. */
  mode: "vector" | "phrase";
  requested_mode: "vector" | "phrase";
  offset: number;
  limit: number;
  next_offset: number | null;
  results: SearchResult[];
}

export type SearchErrorKind = "rate-limited" | "unavailable" | "invalid" | "timeout" | "failed";

export class SearchError extends Error {
  constructor(
    readonly kind: SearchErrorKind,
    message: string,
    /** Seconds to wait, for "rate-limited". */
    readonly retryAfter: number | null = null,
  ) {
    super(message);
    this.name = "SearchError";
  }
}

async function errorMessage(res: Response): Promise<string | null> {
  try {
    const body = (await res.json()) as { error?: unknown };
    return typeof body.error === "string" ? body.error : null;
  } catch {
    return null;
  }
}

/** Fetch one page of results. Rejects with a SearchError (or an AbortError when `signal` aborts). */
export async function fetchSearch(
  state: SearchState,
  offset = 0,
  signal?: AbortSignal,
  timeoutMs = TIMEOUT_MS,
): Promise<SearchResponse> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort("timeout"), timeoutMs);
  const onAbort = () => controller.abort(signal?.reason);
  signal?.addEventListener("abort", onAbort);
  let res: Response;
  try {
    res = await fetch(searchApiUrl(state, offset), { signal: controller.signal });
  } catch (err) {
    if (signal?.aborted) throw err;
    if (controller.signal.reason === "timeout") {
      throw new SearchError("timeout", "The search took too long.");
    }
    throw new SearchError("failed", "Could not reach the search service.");
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener("abort", onAbort);
  }
  if (res.ok) return (await res.json()) as SearchResponse;
  const message = await errorMessage(res);
  if (res.status === 429) {
    const retry = Number(res.headers.get("retry-after"));
    throw new SearchError(
      "rate-limited",
      message ?? "Too many searches.",
      Number.isFinite(retry) && retry > 0 ? retry : null,
    );
  }
  if (res.status === 503) {
    throw new SearchError("unavailable", message ?? "Search is unavailable.");
  }
  if (res.status === 422) throw new SearchError("invalid", "The search couldn't be read.");
  throw new SearchError("failed", `The search failed (${res.status}).`);
}

/** Reader URL of a result: the work, scrolled to the passage. */
export function resultHref(result: Pick<SearchResult, "work_id" | "canonical_ref">): string {
  return `${workHref(result.work_id)}#${encodeURIComponent(result.canonical_ref)}`;
}

/** "350–373", "397", "500 BC", or "" when undated. */
export function formatRange(range: [number, number] | null, year: number | null = null): string {
  if (range && range[0] !== range[1]) return `${formatYear(range[0])}–${formatYear(range[1])}`;
  if (range) return formatYear(range[0]);
  return year === null ? "" : formatYear(year);
}
