// Author pages (#145): an author's works, pseudonymous links, and the author list.

import { type Facets, fold, libraryFacets } from "./filter";
import { languageInfo } from "./lang";
import type { Author, AuthorMap, LibraryIndex, WorkRow } from "./library";

const collator = new Intl.Collator(undefined, { sensitivity: "base", numeric: true });

export interface LanguageGroup {
  /** Language code (Work.language). */
  language: string;
  works: WorkRow[];
}

/**
 * The works of an author (by `author_ids`, so a work with several authors is
 * listed under each), grouped by language. Groups are ordered by language
 * name and works by title, then id.
 */
export function worksByLanguage(rows: WorkRow[], authorId: string): LanguageGroup[] {
  const groups = new Map<string, WorkRow[]>();
  for (const row of rows) {
    if (!row.author_ids.includes(authorId)) continue;
    const list = groups.get(row.language);
    if (list) list.push(row);
    else groups.set(row.language, [row]);
  }
  return [...groups]
    .map(([language, works]) => ({
      language,
      works: works.sort((a, b) => collator.compare(a.title, b.title) || collator.compare(a.id, b.id)),
    }))
    .sort((a, b) => collator.compare(languageInfo(a.language).name, languageInfo(b.language).name));
}

/** The works of an author (by `author_ids`), in index order. */
export function authorWorks(rows: WorkRow[], authorId: string): WorkRow[] {
  return rows.filter((row) => row.author_ids.includes(authorId));
}

/**
 * Facet values for an author page's filters: only the languages, genres and
 * collections that `works` (the author's) occur in.
 */
export function authorFacets(index: LibraryIndex, works: WorkRow[], authors: AuthorMap): Facets {
  const used = new Set(works.map((w) => w.source_id));
  const sources = Object.fromEntries(Object.entries(index.sources).filter(([id]) => used.has(id)));
  return libraryFacets({ ...index, works, sources }, authors);
}

/** Pseudonymous authors whose works carry this author's name (`pseudo_of`), by name. */
export function pseudonymsOf(authors: AuthorMap, authorId: string): Author[] {
  return [...authors.values()]
    .filter((a) => a.pseudo_of === authorId)
    .sort((a, b) => collator.compare(a.name, b.name));
}

/**
 * Authors whose name or an alias matches every term of `query` (folded), by
 * name. Authors with no works are listed only when `withoutWorks` is set.
 */
export function filterAuthors(
  authors: AuthorMap,
  counts: ReadonlyMap<string, number>,
  query: string,
  withoutWorks = false,
): Author[] {
  const terms = fold(query).split(/\s+/).filter(Boolean);
  return [...authors.values()]
    .filter((a) => withoutWorks || (counts.get(a.id) ?? 0) > 0)
    .filter((a) => {
      const hay = fold([a.name, ...a.aliases, a.id].join(" "));
      return terms.every((t) => hay.includes(t));
    })
    .sort((a, b) => collator.compare(a.name, b.name) || collator.compare(a.id, b.id));
}
