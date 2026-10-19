// Types and loaders for the static library export (scripts/export_library.py).

import { LIBRARY_URL } from "./config";

export interface WorkRow {
  id: string;
  /** Author as the source gives it (provenance); use author_ids for identity. */
  author: string | null;
  /** Canonical author ids (keys of authors.json); [] for anonymous works. */
  author_ids: string[];
  title: string;
  language: string;
  genre: string;
  tradition: string | null;
  date: number | null;
  date_range: [number, number] | null;
  date_confidence: "established" | "approximate" | "uncertain";
  source_id: string;
  edition: string | null;
  license: string;
  provenance_url: string | null;
  translation_of: string | null;
  /**
   * Version group (patristica/versions.py, #178): the works that are the same
   * text in other languages or editions share this id. Null when the work has
   * no other version. The id can change when links change; don't put it in URLs.
   */
  version_group: string | null;
  chunks: number;
  file: string;
}

export interface LibraryIndex {
  /** Content hash of the export; changes whenever any index row or text changes. */
  version: string;
  /** source_id → readable collection label (patristica/sources.py). */
  sources: Record<string, string>;
  works: WorkRow[];
}

/** A year or year range from the author index, with its certainty. */
export interface AuthorDate {
  low: number;
  high: number;
  confidence: "established" | "approximate" | "uncertain";
}

/** One person in authors.json (patristica/authors.py, #82). */
export interface Author {
  /** Stable slug, e.g. "augustine-of-hippo". */
  id: string;
  /** English display name. */
  name: string;
  /** Source spellings and Latin/Greek forms, for search. */
  aliases: string[];
  birth: AuthorDate | null;
  death: AuthorDate | null;
  /** Span of known activity. */
  floruit: AuthorDate | null;
  tradition: string | null;
  /** TLG / stoa / PTA author ids, e.g. "tlg2035". */
  external_ids: string[];
  /** For a pseudonymous author, the id of the author whose name the works carry. */
  pseudo_of: string | null;
}

export interface AuthorsFile {
  authors: Author[];
}

/** `[ref_suffix, text]`, plus a trailing `1` when the chunk is out of period. */
export type ChunkRow = [string, string] | [string, string, 1];

export interface WorkFile {
  work_id: string;
  /** Dot-separated ref prefix shared by every chunk, stripped from the suffixes. */
  ref_prefix: string;
  chunks: ChunkRow[];
}

function encodePath(path: string): string {
  return path.split("/").map(encodeURIComponent).join("/");
}

/** URL of a file in the library export. */
export function libraryUrl(file: string): string {
  return `${LIBRARY_URL}/${encodePath(file)}`;
}

/** Reader URL for a work. Work ids contain slashes and arbitrary characters. */
export function workHref(id: string): string {
  return `/works/${encodePath(id)}`;
}

/** Inverse of workHref for the catch-all route's segments. */
export function workIdFromSegments(segments: string[]): string {
  return segments.map(decodeURIComponent).join("/");
}

async function fetchJson<T>(url: string): Promise<T> {
  const res = await fetch(url);
  if (!res.ok) {
    throw new Error(`${res.status} ${res.statusText} fetching ${url}`);
  }
  return (await res.json()) as T;
}

let indexPromise: Promise<LibraryIndex> | null = null;

/** Load index.json once per page session. A failed load is retried on the next call. */
export function loadIndex(): Promise<LibraryIndex> {
  if (!indexPromise) {
    indexPromise = fetchJson<LibraryIndex>(libraryUrl("index.json")).catch((err) => {
      indexPromise = null;
      throw err;
    });
  }
  return indexPromise;
}

export const AUTHORS_FILE = "authors.json";

let authorsPromise: Promise<AuthorsFile> | null = null;

/** Load authors.json once per page session. A failed load is retried on the next call. */
export function loadAuthors(): Promise<AuthorsFile> {
  if (!authorsPromise) {
    authorsPromise = fetchJson<AuthorsFile>(libraryUrl(AUTHORS_FILE)).catch((err) => {
      authorsPromise = null;
      throw err;
    });
  }
  return authorsPromise;
}

/** The index and the author index, loaded together. */
export interface Library {
  index: LibraryIndex;
  authors: AuthorMap;
}

/** Load index.json and authors.json. */
export async function loadLibrary(): Promise<Library> {
  const [index, authors] = await Promise.all([loadIndex(), loadAuthors()]);
  return { index, authors: authorMap(authors) };
}

/** Author id → author. */
export type AuthorMap = ReadonlyMap<string, Author>;

export function authorMap(file: AuthorsFile): AuthorMap {
  return new Map(file.authors.map((a) => [a.id, a]));
}

/** Author page URL. Author ids are stable slugs: they are URLs. */
export function authorHref(id: string): string {
  return `/authors/${encodeURIComponent(id)}`;
}

/** A work's author, for display: its id (null when the index lacks it) and name. */
export interface AuthorRef {
  id: string | null;
  name: string;
}

/**
 * A work's authors for display, in order. Anonymous works give []. An id
 * missing from the author index (`scripts.validate` rules that out) falls
 * back to the source's author string, unlinked.
 */
export function workAuthors(row: Pick<WorkRow, "author" | "author_ids">, authors: AuthorMap): AuthorRef[] {
  const found = row.author_ids.map((id) => authors.get(id));
  if (found.length > 0 && found.every((a) => a !== undefined)) {
    return found.map((a) => ({ id: a!.id, name: a!.name }));
  }
  if (found.length > 0 && row.author) return [{ id: null, name: row.author }];
  return [];
}

export function loadWork(file: string): Promise<WorkFile> {
  return fetchJson<WorkFile>(libraryUrl(file));
}
