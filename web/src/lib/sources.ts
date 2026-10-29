// Per-collection licence summary for the Sources & licences page.

import type { LibraryIndex } from "./library";

/** Licences that forbid commercial use (see DATA_LICENSE.md). */
export const NON_COMMERCIAL = new Set([
  "cc-by-nc-4.0",
  "cc-by-nc-sa-4.0",
  "cc-by-nc-sa-3.0",
  "academic-noncommercial",
  // Hudra (#262): granted to Patristica for non-commercial use.
  "used-with-permission",
]);

export interface SourceSummary {
  sourceId: string;
  label: string;
  works: number;
  chunks: number;
  /** Licence → number of works, most common first. */
  licenses: [string, number][];
  /** Distinct editions, most common first (at most `MAX_LISTED`). */
  editions: string[];
  /** Number of distinct editions not listed in `editions`. */
  moreEditions: number;
  /** Provenance links: the distinct URLs, or their common prefix when there are many. */
  links: string[];
  nonCommercial: boolean;
}

const MAX_LISTED = 3;

function countsDesc(values: string[]): [string, number][] {
  const counts = new Map<string, number>();
  for (const v of values) counts.set(v, (counts.get(v) ?? 0) + 1);
  return [...counts].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
}

/** Longest common prefix of URLs, cut back to a path boundary. */
export function commonUrlPrefix(urls: string[]): string {
  if (urls.length === 0) return "";
  let prefix = urls[0];
  for (const u of urls.slice(1)) {
    let i = 0;
    while (i < prefix.length && i < u.length && prefix[i] === u[i]) i++;
    prefix = prefix.slice(0, i);
  }
  if (urls.every((u) => u === prefix)) return prefix;
  const cut = prefix.lastIndexOf("/");
  return cut > "https://".length ? prefix.slice(0, cut + 1) : "";
}

export function summarizeSources(index: LibraryIndex): SourceSummary[] {
  const bySource = new Map<string, LibraryIndex["works"]>();
  for (const w of index.works) {
    const list = bySource.get(w.source_id) ?? [];
    list.push(w);
    bySource.set(w.source_id, list);
  }
  return [...bySource].map(([sourceId, works]) => {
    const licenses = countsDesc(works.map((w) => w.license));
    const urls = [...new Set(works.flatMap((w) => (w.provenance_url ? [w.provenance_url] : [])))];
    const prefix = commonUrlPrefix(urls);
    const editions = countsDesc(works.flatMap((w) => (w.edition ? [w.edition] : []))).map(([e]) => e);
    return {
      sourceId,
      label: index.sources[sourceId] ?? sourceId,
      works: works.length,
      chunks: works.reduce((n, w) => n + w.chunks, 0),
      licenses,
      editions: editions.slice(0, MAX_LISTED),
      moreEditions: Math.max(0, editions.length - MAX_LISTED),
      links: urls.length <= MAX_LISTED ? urls.sort() : prefix ? [prefix] : urls.sort().slice(0, MAX_LISTED),
      nonCommercial: licenses.some(([l]) => NON_COMMERCIAL.has(l)),
    };
  }).sort((a, b) => a.label.localeCompare(b.label));
}
