// Passage search through the search API (`GET /api/search`, api/search.py, #141).

import { API_URL } from "./config";
import { DEFAULT_VIEW, MULTI_KEYS, parseViewState, viewStateToParams } from "./filter";
import { formatYear } from "./format";
import { languageInfo } from "./lang";
import { workHref } from "./library";

/** The search page's URL state: the query and the library index's facets. */
export interface SearchState {
  q: string;
  author: string[];
  language: string[];
  genre: string[];
  source: string;
  from: number | null;
  to: number | null;
}

export const DEFAULT_SEARCH: SearchState = {
  q: "",
  author: [],
  language: [],
  genre: [],
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

/** Serialize the search state, omitting defaults: `/?{this}` is a shareable search. */
export function searchStateToParams(state: SearchState): URLSearchParams {
  return viewStateToParams({ ...DEFAULT_VIEW, ...state });
}

export function searchHref(state: Partial<SearchState>): string {
  const query = searchStateToParams({ ...DEFAULT_SEARCH, ...state }).toString();
  return query ? `/?${query}` : "/";
}

/** The API request for one page of results. */
export function searchApiUrl(state: SearchState, offset = 0, limit = PAGE_SIZE): string {
  const params = new URLSearchParams({ q: state.q.trim() });
  // The API takes repeated parameters for the multi-valued facets.
  for (const key of MULTI_KEYS) {
    for (const v of state[key]) params.append(key, v);
  }
  if (state.source) params.set("source", state.source);
  if (state.from !== null) params.set("date_from", String(state.from));
  if (state.to !== null) params.set("date_to", String(state.to));
  params.set("limit", String(limit));
  if (offset) params.set("offset", String(offset));
  return `${API_URL}/search?${params}`;
}

/** Another version of a result's passage (#180): the same verse in another edition or language. */
export interface SearchVersion {
  chunk_id: string;
  work_id: string;
  /** In the version's own numbering, which may differ from the result's (Ps 22 / Ps 23). */
  canonical_ref: string;
  language: string;
  source_label: string;
  edition: string | null;
  /** Similarity to the query, or null in an unranked phrase search. */
  score: number | null;
}

/** A unit next to a search result in its work. */
export interface ContextUnit {
  chunk_id: string;
  canonical_ref: string;
  text: string;
}

/**
 * A result's English: a linked English version in the library when there is
 * one (`machine: false`; for Scripture the KJV), else our machine translation.
 */
export interface ResultTranslation {
  language: string;
  text: string;
  /** The English of the units before and after the result (its context), where there is one. */
  before?: string | null;
  after?: string | null;
  machine: boolean;
  /** The translation model; null for a linked version. */
  model: string | null;
  /** A linked version's work and the ref of its passage; null for a machine translation. */
  work_id?: string | null;
  canonical_ref?: string | null;
  source_label?: string | null;
  edition?: string | null;
}

export interface SearchResult {
  chunk_id: string;
  work_id: string;
  canonical_ref: string;
  language: string;
  text: string;
  text_truncated: boolean;
  /**
   * The units before and after this one in its work (api/context.py, #209),
   * shown around it for context; null where there is none.
   */
  context?: { before: ContextUnit | null; after: ContextUnit | null };
  /** An English version of a result in another language; null for English results. */
  translation: ResultTranslation | null;
  /** Similarity to the query (vector search, or a phrase search with free text); else null. */
  score: number | null;
  /** What matched: the text's vector, its English translation's vector, or the quoted phrases. */
  matched: "text" | "translation" | "phrase";
  /** Where `text` starts in the passage, when a long passage is shown from a later match. */
  text_start: number;
  /** Phrase matches in `text`, as [start, end) JavaScript string indices (UTF-16). */
  matches: [number, number][];
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
  /**
   * The other versions of this passage the search found, best first. This
   * result is the best-scoring of them (for a phrase search, the first in order).
   */
  versions: SearchVersion[];
}

export interface SearchResponse {
  query: string;
  /** "keyword" when the query has quoted phrases (exact phrase search), else "vector". */
  mode: "vector" | "keyword";
  /** The quoted phrases, as the API parsed them. */
  phrases: string[];
  /** The text outside the quotes (it ranks phrase matches by meaning). */
  text: string;
  /** How many passages contain the phrases (keyword mode only). */
  total: number | null;
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

/** Why the state can't be searched as it is, or null. Checked before any request. */
export function stateError(state: SearchState): string | null {
  if (state.from !== null && state.to !== null && state.from > state.to) {
    return "The start year is after the end year. Swap them or clear one.";
  }
  return null;
}

async function errorMessage(res: Response): Promise<string | null> {
  try {
    const body = (await res.json()) as { error?: unknown };
    return typeof body.error === "string" ? body.error : null;
  } catch {
    return null;
  }
}

/** The SearchError for a non-OK response, with the API's reason when it gives one. */
async function responseError(res: Response): Promise<SearchError> {
  const message = await errorMessage(res);
  if (res.status === 429) {
    const retry = Number(res.headers.get("retry-after"));
    return new SearchError(
      "rate-limited",
      message ?? "Too many searches.",
      Number.isFinite(retry) && retry > 0 ? retry : null,
    );
  }
  if (res.status === 503) return new SearchError("unavailable", message ?? "Search is unavailable.");
  if (res.status === 422) {
    return new SearchError(
      "invalid",
      message ?? "The search couldn't be read. Check the query and the date filters.",
    );
  }
  return new SearchError("failed", `The search failed (${res.status}).`);
}

/**
 * Fetch one page of results. Rejects with a SearchError (or an AbortError when
 * `signal` aborts). The timeout and `signal` cover the whole response, body
 * included, so a stalled body can't leave the page waiting.
 */
export async function fetchSearch(
  state: SearchState,
  offset = 0,
  signal?: AbortSignal,
  timeoutMs = TIMEOUT_MS,
): Promise<SearchResponse> {
  const invalid = stateError(state);
  if (invalid) throw new SearchError("invalid", invalid);
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort("timeout"), timeoutMs);
  const onAbort = () => controller.abort(signal?.reason);
  signal?.addEventListener("abort", onAbort);
  try {
    const res = await fetch(searchApiUrl(state, offset), { signal: controller.signal });
    if (!res.ok) throw await responseError(res);
    return (await res.json()) as SearchResponse;
  } catch (err) {
    if (err instanceof SearchError || signal?.aborted) throw err;
    if (controller.signal.reason === "timeout") {
      throw new SearchError("timeout", "The search took too long.");
    }
    throw new SearchError("failed", "Could not reach the search service.");
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener("abort", onAbort);
  }
}

/** Characters that open or close a quoted phrase (as api/search.py parses them). */
const QUOTES = /["“”„«»]/g;

/** The query with its quote marks removed: the same words, searched by meaning. */
export function withoutQuotes(q: string): string {
  return q.replace(QUOTES, " ").replace(/\s+/g, " ").trim();
}

export interface Segment {
  text: string;
  match: boolean;
}

/**
 * Split `text` into plain and matched segments at the API's `[start, end)`
 * offsets (JavaScript string indices). Offsets out of order or past the end
 * are clamped, so a bad span can't drop text.
 */
export function highlight(text: string, matches: [number, number][]): Segment[] {
  const segments: Segment[] = [];
  let at = 0;
  for (const [start, end] of matches) {
    const a = Math.max(at, Math.min(start, text.length));
    const b = Math.max(a, Math.min(end, text.length));
    if (a > at) segments.push({ text: text.slice(at, a), match: false });
    if (b > a) segments.push({ text: text.slice(a, b), match: true });
    at = b;
  }
  if (at < text.length) segments.push({ text: text.slice(at), match: false });
  return segments;
}

/** Reader URL of a result: the work, scrolled to the passage. */
export function resultHref(result: Pick<SearchResult, "work_id" | "canonical_ref">): string {
  return `${workHref(result.work_id)}#${encodeURIComponent(result.canonical_ref)}`;
}

/** The reader link of a linked English version's passage, or null for a machine translation. */
export function translationHref(translation: ResultTranslation): string | null {
  if (translation.machine || !translation.work_id || !translation.canonical_ref) return null;
  return resultHref({ work_id: translation.work_id, canonical_ref: translation.canonical_ref });
}

/** "350–373", "397", "500 BC", or "" when undated. */
export function formatRange(range: [number, number] | null, year: number | null = null): string {
  if (range && range[0] !== range[1]) return `${formatYear(range[0])}–${formatYear(range[1])}`;
  if (range) return formatYear(range[0]);
  return year === null ? "" : formatYear(year);
}

/** One language of a result's other versions: "English: King James Version, World English Bible". */
export interface VersionLanguage {
  language: string;
  name: string;
  versions: { href: string; label: string; ref: string | null }[];
}

/**
 * A result's other versions grouped by language, the languages in the order
 * of their best version. Each version is labelled by its source, or by its
 * edition when two versions in a language share a source, and has its ref
 * when it is numbered differently from the result.
 */
export function versionLanguages(result: Pick<SearchResult, "canonical_ref" | "versions">): VersionLanguage[] {
  const byLanguage = new Map<string, SearchVersion[]>();
  for (const v of result.versions ?? []) {
    byLanguage.set(v.language, [...(byLanguage.get(v.language) ?? []), v]);
  }
  return [...byLanguage].map(([language, versions]) => {
    const sources = new Map<string, number>();
    for (const v of versions) sources.set(v.source_label, (sources.get(v.source_label) ?? 0) + 1);
    return {
      language,
      name: languageInfo(language).name,
      versions: versions.map((v) => ({
        href: resultHref(v),
        label: (sources.get(v.source_label) ?? 0) > 1 && v.edition ? v.edition : v.source_label,
        ref: v.canonical_ref === result.canonical_ref ? null : v.canonical_ref,
      })),
    };
  });
}
