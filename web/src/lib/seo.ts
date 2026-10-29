// What search engines see (#406): page titles and descriptions, schema.org
// JSON-LD, the sitemap and robots.txt. Pure functions of the library index,
// used by the server routes (src/app) and, for titles, by the client pages.

import type { MetadataRoute } from "next";

import { formatDate, GENRES, LICENSES } from "./format";
import { languageInfo } from "./lang";
import {
  authorHref,
  workAuthors,
  workHref,
  type Author,
  type AuthorMap,
  type LibraryIndex,
  type WorkRow,
} from "./library";
import { originalIds } from "./versions";

/** The production origin: canonical URLs, the sitemap and JSON-LD use it. */
export const SITE_URL = "https://patristica.app";

/** Absolute URL of a site path ("/works/…"). */
export function absoluteUrl(path: string): string {
  return `${SITE_URL}${path}`;
}

/** "A", "A and B", "A, B and C". */
function listJoin(items: readonly string[]): string {
  if (items.length < 2) return items.join("");
  return `${items.slice(0, -1).join(", ")} and ${items[items.length - 1]}`;
}

/** Every work in `row`'s version group, `row` included; [] when it has no other version. */
function members(index: LibraryIndex, row: WorkRow): WorkRow[] {
  if (!row.version_group) return [];
  return index.works.filter((w) => w.version_group === row.version_group);
}

/**
 * Page title of a work: "Augustine of Hippo, Confessiones (Latin)". Every
 * version of a text has the same title, so the language is always named, and
 * the collection too where another version in the same language exists
 * (Genesis in English from the KJV and from the WEB).
 */
export function workTitle(row: WorkRow, authors: AuthorMap, index: LibraryIndex): string {
  const names = workAuthors(row, authors).map((a) => a.name);
  const lang = languageInfo(row.language).name;
  const sameLanguage = members(index, row).some((w) => w.id !== row.id && w.language === row.language);
  const qualifier = sameLanguage ? `${lang}, ${index.sources[row.source_id] ?? row.source_id}` : lang;
  return `${names.length > 0 ? `${names.join(", ")}, ` : ""}${row.title} (${qualifier})`;
}

/** The languages of a work's other versions, most versions first, its own language last. */
function otherLanguages(row: WorkRow, index: LibraryIndex): string[] {
  const counts = new Map<string, number>();
  for (const w of members(index, row)) {
    if (w.id !== row.id) counts.set(w.language, (counts.get(w.language) ?? 0) + 1);
  }
  return [...counts]
    .sort(([a, x], [b, y]) => Number(a === row.language) - Number(b === row.language) || y - x)
    .map(([code]) => (code === row.language ? `another ${languageInfo(code).name} version` : languageInfo(code).name));
}

/**
 * Meta description of a work: "Read Confessiones by Augustine of Hippo in
 * Latin (c. 397), from Corpus Corporum, free on Patristica. Also in English
 * and Greek."
 */
export function workDescription(row: WorkRow, authors: AuthorMap, index: LibraryIndex): string {
  const names = workAuthors(row, authors).map((a) => a.name);
  const original = row.translation_of ? index.works.find((w) => w.id === row.translation_of) : undefined;
  const notes = [
    formatDate(row),
    original && original.language !== row.language
      ? `translated from the ${languageInfo(original.language).name}`
      : "",
  ].filter(Boolean);
  const also = otherLanguages(row, index);
  return (
    `Read ${row.title}${names.length > 0 ? ` by ${listJoin(names)}` : ""} ` +
    `in ${languageInfo(row.language).name}${notes.length > 0 ? ` (${notes.join("; ")})` : ""}, ` +
    `from ${index.sources[row.source_id] ?? row.source_id}, free on Patristica.` +
    (also.length > 0 ? ` Also in ${listJoin(also)}.` : "")
  );
}

/** A work as a JSON-LD node that other nodes point to. */
function workNode(row: WorkRow) {
  return {
    "@type": "CreativeWork",
    "@id": absoluteUrl(workHref(row.id)),
    name: row.title,
    inLanguage: languageInfo(row.language).lang,
  };
}

/**
 * What a group member translates: its `translation_of` when that is in the
 * group, else (Scripture, where most witnesses carry no link) the group's
 * originals, as the reader's "Original" line names them (lib/versions.ts).
 */
function translatedFrom(member: WorkRow, group: readonly WorkRow[], originals: ReadonlySet<string>): WorkRow[] {
  const linked = member.translation_of ? group.find((w) => w.id === member.translation_of) : undefined;
  if (linked) return [linked];
  if (member.translation_of || originals.has(member.id)) return [];
  return group.filter((w) => originals.has(w.id));
}

/**
 * schema.org JSON-LD for a work page: the text, its authors, and the versions
 * it translates or that translate it (`translationOfWork` / `workTranslation`).
 */
export function workJsonLd(row: WorkRow, authors: AuthorMap, index: LibraryIndex): Record<string, unknown> {
  const group = members(index, row);
  const originals = originalIds(group);
  const url = absoluteUrl(workHref(row.id));
  const license = LICENSES[row.license]?.url;
  const from = translatedFrom(row, group, originals);
  const translations = group.filter((w) => w.id !== row.id && translatedFrom(w, group, originals).includes(row));
  return {
    "@context": "https://schema.org",
    ...workNode(row),
    url,
    author: workAuthors(row, authors).map((a) => ({
      "@type": "Person",
      name: a.name,
      ...(a.id ? { "@id": absoluteUrl(authorHref(a.id)), url: absoluteUrl(authorHref(a.id)) } : {}),
    })),
    genre: GENRES[row.genre] ?? row.genre,
    isPartOf: { "@type": "Collection", name: index.sources[row.source_id] ?? row.source_id },
    isAccessibleForFree: true,
    ...(license ? { license } : {}),
    ...(from.length > 0 ? { translationOfWork: from.map(workNode) } : {}),
    ...(translations.length > 0 ? { workTranslation: translations.map(workNode) } : {}),
  };
}

/** The works of an author, as the author page lists them. */
export function worksOf(index: LibraryIndex, authorId: string): WorkRow[] {
  return index.works.filter((w) => w.author_ids.includes(authorId));
}

/**
 * Meta description of an author page: "Augustine of Hippo (354–430): 120
 * works in Latin and English, free to read on Patristica. Also known as …"
 */
export function authorDescription(author: Author, works: readonly WorkRow[], lifespan: string): string {
  const counts = new Map<string, number>();
  for (const w of works) counts.set(w.language, (counts.get(w.language) ?? 0) + 1);
  const languages = [...counts].sort(([, x], [, y]) => y - x).map(([code]) => languageInfo(code).name);
  const head = `${author.name}${lifespan ? ` (${lifespan})` : ""}`;
  const body =
    works.length === 0
      ? "in the author index of Patristica."
      : `${works.length.toLocaleString("en")} ${works.length === 1 ? "work" : "works"} in ${listJoin(languages)}, free to read on Patristica.`;
  const aliases = author.aliases.slice(0, 3);
  return `${head}: ${body}${aliases.length > 0 ? ` Also known as ${aliases.join(", ")}.` : ""}`;
}

/** An exact year as an ISO 8601 date ("0354"); approximate and BC years give none. */
function isoYear(date: Author["birth"]): string | undefined {
  if (!date || date.confidence !== "established" || date.low !== date.high || date.low < 1) return undefined;
  return String(date.low).padStart(4, "0");
}

/** schema.org JSON-LD for an author page. */
export function authorJsonLd(author: Author, description: string): Record<string, unknown> {
  const url = absoluteUrl(authorHref(author.id));
  const birthDate = isoYear(author.birth);
  const deathDate = isoYear(author.death);
  return {
    "@context": "https://schema.org",
    "@type": "Person",
    "@id": url,
    url,
    name: author.name,
    description,
    ...(author.aliases.length > 0 ? { alternateName: author.aliases } : {}),
    ...(birthDate ? { birthDate } : {}),
    ...(deathDate ? { deathDate } : {}),
  };
}

/** The top-level pages, in the sitemap with the works and authors. */
export const SITE_PAGES = ["/", "/works", "/authors", "/sources"] as const;

/** Every page worth indexing: the top-level pages, every work, every author with works. */
export function sitemapEntries(index: LibraryIndex, authors: AuthorMap): MetadataRoute.Sitemap {
  const withWorks = new Set(index.works.flatMap((w) => w.author_ids));
  return [
    ...SITE_PAGES.map((path) => ({ url: absoluteUrl(path) })),
    ...index.works.map((w) => ({ url: absoluteUrl(workHref(w.id)) })),
    ...[...authors.keys()].filter((id) => withWorks.has(id)).map((id) => ({ url: absoluteUrl(authorHref(id)) })),
  ];
}

/**
 * robots.txt: everything but the search API (each query costs an embedding
 * call) and query-string URLs. Those are search results, library filter
 * combinations and parallel-reading pairs: endless, and duplicates of the
 * canonical pages in the sitemap. `/_next/` stays open for rendering.
 */
export const ROBOTS: MetadataRoute.Robots = {
  rules: { userAgent: "*", allow: ["/", "/_next/"], disallow: ["/api/", "/*?"] },
  sitemap: absoluteUrl("/sitemap.xml"),
};
