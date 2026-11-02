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
  /**
   * For a work with no date of its own: its authors' activity range from the
   * author index (#151). Approximate; used by the date filter and sort, and
   * shown as the author's dates, never as the work's. Absent in libraries
   * exported before it.
   */
  author_date_range?: [number, number] | null;
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
  /**
   * True for our machine translations (#422): English made by an AI model from
   * the original, unreviewed. Absent on every other work, and in libraries
   * exported before it.
   */
  machine_translation?: boolean;
  chunks: number;
  file: string;
}

export interface LibraryIndex {
  /** Content hash of the export; changes whenever any index row or text changes. */
  version: string;
  /** source_id → readable collection label (patristica/sources.py). */
  sources: Record<string, string>;
  works: WorkRow[];
  /**
   * Version groups that have a passage alignment file (alignmentFile(group)),
   * #179. Absent in a library published before alignments were exported.
   */
  alignments?: string[];
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

/**
 * Editorial material in a chunk's text (patristica/editorial.py, #236):
 * `[start, end, kind]`, offsets in UTF-16 code units (JavaScript string
 * indices), end exclusive. Kinds: title, heading, supplement, lacuna,
 * metadata, note.
 */
export type EditorialSpan = [number, number, string];

export interface WorkFile {
  work_id: string;
  /** Dot-separated ref prefix shared by every chunk, stripped from the suffixes. */
  ref_prefix: string;
  /**
   * Scripture books only: ref suffix → ref in org versification (BHS /
   * Nestle-Aland), for the chunks whose org ref differs from their own
   * (patristica/versification.py). Absent for works that aren't Scripture books.
   */
  org_refs?: Record<string, string>;
  /** Ref suffix → editorial spans of that chunk; absent when the work has none. */
  editorial?: Record<string, EditorialSpan[]>;
  /**
   * The source marks every heading (#128): a heading is a chunk that is a
   * `title` or `heading` editorial span as a whole (`render.ts`).
   */
  marks_headings?: boolean;
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

/** Work files kept in memory: the ones being read (up to 4 side by side, #181) and the next one opened. */
const WORK_CACHE_SIZE = 5;
const workCache = new Map<string, Promise<WorkFile>>();

/**
 * Load a work file. The last few loads are kept, so a version switch that
 * loads its target to find the passage (lib/versions.ts) doesn't make the
 * reader fetch it again. A failed load is retried on the next call.
 */
export function loadWork(file: string): Promise<WorkFile> {
  let promise = workCache.get(file);
  if (promise) {
    workCache.delete(file);
  } else {
    promise = fetchJson<WorkFile>(libraryUrl(file)).catch((err) => {
      workCache.delete(file);
      throw err;
    });
  }
  workCache.set(file, promise);
  while (workCache.size > WORK_CACHE_SIZE) workCache.delete(workCache.keys().next().value!);
  return promise;
}

/** One member of an alignment file: its units' groups and confidences (lib/alignment.ts). */
export interface AlignmentMember {
  /** Number of units (chunks of the work file) the spans count. */
  units: number;
  /** One token per unit: `.` none, `+` next group, `+N`/`-N` jumps, `=` same group. */
  spans: string;
  /** One confidence digit (tenths) per group of the member, in order of first appearance. */
  conf: string;
}

/**
 * The passage alignment of a version group (scripts/export_library.py,
 * patristica/alignment_store.py): alignment groups numbered in the pivot's
 * order, and per member which group each unit is in.
 */
export interface AlignmentFile {
  group: string;
  pivot: string;
  groups: number;
  members: Record<string, AlignmentMember>;
}

/** Library path of a version group's alignment: `book:gen` → `alignments/book/gen.json`. */
export function alignmentPath(group: string): string {
  const rel = group.startsWith("book:") ? group.replace(":", "/") : group;
  return `alignments/${rel}.json`;
}

/** True if the index says `group` has an alignment file. */
export function hasAlignment(index: LibraryIndex, group: string | null): group is string {
  return Boolean(group && index.alignments?.includes(group));
}

const ALIGNMENT_CACHE_SIZE = 4;
const alignmentCache = new Map<string, Promise<AlignmentFile>>();

/**
 * Load a version group's alignment file. The last few are kept, so switching
 * back and forth within a group loads it once. A failed load is retried on
 * the next call.
 */
export function loadAlignment(group: string): Promise<AlignmentFile> {
  const file = alignmentPath(group);
  let promise = alignmentCache.get(file);
  if (promise) {
    alignmentCache.delete(file);
  } else {
    promise = fetchJson<AlignmentFile>(libraryUrl(file)).catch((err) => {
      alignmentCache.delete(file);
      throw err;
    });
  }
  alignmentCache.set(file, promise);
  while (alignmentCache.size > ALIGNMENT_CACHE_SIZE) alignmentCache.delete(alignmentCache.keys().next().value!);
  return promise;
}
