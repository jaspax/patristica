// Types and loaders for the static library export (scripts/export_library.py).

import { LIBRARY_URL } from "./config";

export interface WorkRow {
  id: string;
  author: string | null;
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

export function loadWork(file: string): Promise<WorkFile> {
  return fetchJson<WorkFile>(libraryUrl(file));
}
