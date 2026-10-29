// The library index on the server (#406): page metadata, JSON-LD, the sitemap
// and the crawlable fallbacks of the client pages read it. Server code only.

import { readFile } from "node:fs/promises";
import path from "node:path";

import { connection } from "next/server";

import { LIBRARY_URL } from "./config";
import { authorMap, libraryUrl, type AuthorsFile, type Library, type LibraryIndex } from "./library";

/** How long a loaded library is used: the CDN's cache time (infra/tofu `library_cdn_ttl`). */
export const REFRESH_MS = 10 * 60 * 1000;

async function readLibraryFile<T>(file: string): Promise<T> {
  // A same-origin library (`/library`, `npm run dev`) is the export linked into public/.
  if (LIBRARY_URL.startsWith("/")) {
    return JSON.parse(await readFile(path.join(process.cwd(), "public", LIBRARY_URL, file), "utf8")) as T;
  }
  const res = await fetch(libraryUrl(file));
  if (!res.ok) throw new Error(`${res.status} ${res.statusText} fetching ${libraryUrl(file)}`);
  return (await res.json()) as T;
}

let loaded: { at: number; library: Promise<Library> } | null = null;

/**
 * index.json and authors.json, loaded once per REFRESH_MS and shared by every
 * request. A failed load is retried on the next call. Call it only at request
 * time (after `connection()`): the build has no library.
 */
export function serverLibrary(now: number = Date.now()): Promise<Library> {
  if (!loaded || now - loaded.at > REFRESH_MS) {
    const library = Promise.all([
      readLibraryFile<LibraryIndex>("index.json"),
      readLibraryFile<AuthorsFile>("authors.json"),
    ]).then(([index, authors]) => ({ index, authors: authorMap(authors) }));
    const entry = { at: now, library };
    loaded = entry;
    library.catch(() => {
      if (loaded === entry) loaded = null;
    });
  }
  return loaded.library;
}

/**
 * serverLibrary() at request time, or null when it can't be loaded: the
 * pages then render as before, from the browser, and the error is logged.
 */
export async function serverLibraryOrNull(): Promise<Library | null> {
  await connection();
  try {
    return await serverLibrary();
  } catch (err) {
    console.error("Loading the library on the server failed:", err);
    return null;
  }
}
