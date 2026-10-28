/**
 * Permanent redirects for work ids that have been renamed or split.
 *
 * Work ids appear in reader URLs (`/works/{work_id}`), so renaming a source
 * breaks links to its works. Each entry maps an old id prefix (whole path
 * segments) to its new one, or to "" when the prefix was dropped;
 * `next.config.ts` turns them into `redirects`, first match first.
 */
export const RENAMED_ID_PREFIXES: ReadonlyArray<readonly [from: string, to: string]> = [
  // #102: ids no longer start with a genre (`scripture/kjv/gen` → `kjv/gen`).
  // This also covers Coptic Scriptorium's older `liturgical/` and `patristic/`
  // ids (#52) in one hop.
  ["scripture", ""],
  ["patristic", ""],
  ["liturgical", ""],
  // #102: council work ids are `{source_id}/…` (`councils/nicaea1` → `ecumenical/nicaea1`).
  ["councils", "ecumenical"],
  // #102: Patrologia Latina work ids are spelled like its source id.
  ["oglt_pl", "oglt-pl"],
];

/**
 * Single works whose id changed (old id → new id), for renames that no prefix
 * in `RENAMED_ID_PREFIXES` covers. Scripture work ids are `{source}/{osis book}`,
 * so a book found to be ingested under the wrong code gets a new id; an OGLT PL
 * work id carries its author (`oglt-pl/{author}/{stem}`), so a re-attribution
 * in `oglt_pl_index.csv` does too.
 */
export const RENAMED_WORK_IDS: ReadonlyArray<readonly [from: string, to: string]> = [
  // #188: the Ge'ez "Kings" is 2 Kings only.
  ["gez/kings", "gez/2kgs"],
  // #76: the Ge'ez "Apocalypse of Ezra" is 1 Esdras.
  ["gez/apez", "gez/1esd"],
  // #184: PL 47's "Opusculum I sive liber de oratione" is Cyprian's De dominica oratione.
  ["oglt-pl/augustinus/pl47_0_unk", "oglt-pl/cyprianus-carthaginensis/pl47_0_unk"],
  // #216: PL 47's "Opusculum II sive liber de quatuor virtutibus charitatis" is Quodvultdeus's sermon.
  ["oglt-pl/augustinus/pl47_1_unk", "oglt-pl/quodvultdeus/pl47_1_unk"],
  // #81: PG 5's and PG 10's fragment collections are one work per author; the old id opens the first.
  ["ogpg/vol-005/fragmenta-varia", "ogpg/vol-005/quadratus-fragmentum"],
  ["ogpg/vol-010/alexandrina-fragmenta", "ogpg/vol-010/alexander-hierosolymitanus"],
  // #315: ANF's Hippolytus "Dogmatical and Historical" is one work per treatise; the old id opens the first.
  ["anf-works/hippolytus-dogmatical-and-historical", "anf-works/hippolytus-christ-and-antichrist"],
];

/** Genre prefixes that source ids carried before #102 (`scripture/kjv` → `kjv`). */
export const LEGACY_GENRE_PREFIXES: readonly string[] = ["scripture", "patristic", "liturgical", "councils"];

/** The current id of a source id from an old link (`?source=` filters, #70). */
export function currentSourceId(sourceId: string): string {
  const slash = sourceId.indexOf("/");
  if (slash > 0 && LEGACY_GENRE_PREFIXES.includes(sourceId.slice(0, slash))) {
    return sourceId.slice(slash + 1);
  }
  return sourceId;
}

/** The current id of a work id from an old link, following `RENAMED_ID_PREFIXES` and `RENAMED_WORK_IDS`. */
export function currentWorkId(workId: string): string {
  let id = workId;
  for (const [from, to] of RENAMED_ID_PREFIXES) {
    if (id.startsWith(`${from}/`)) {
      const rest = id.slice(from.length + 1);
      id = to ? `${to}/${rest}` : rest;
      break;
    }
  }
  return RENAMED_WORK_IDS.find(([from]) => from === id)?.[1] ?? id;
}

/**
 * Patrologia Graeca volumes split into individual works (#67). The volume's
 * old work id `ogpg/vol-NNN` no longer exists: its works are `ogpg/vol-NNN/…`,
 * so the old reader URL goes to the library index filtered to them.
 *
 * Must list exactly the volumes in `scripts/ingest/data/ogpg_index.csv`
 * (`tests/test_ogpg_split.py` checks).
 */
export const SPLIT_OGPG_VOLUMES: readonly string[] = [
  "vol-001",
  "vol-002",
  "vol-003",
  "vol-004",
  "vol-005",
  "vol-006",
  "vol-007",
  "vol-008",
  "vol-009",
  "vol-010",
  "vol-011",
  "vol-012",
  "vol-013",
  "vol-014",
  "vol-015",
  "vol-016-pt1",
  "vol-016-pt2",
  "vol-016-pt3",
  "vol-017",
  "vol-018",
  "vol-019",
  "vol-020",
  "vol-021",
  "vol-022",
  "vol-023",
  "vol-024",
  "vol-025",
  "vol-026",
  "vol-027",
  "vol-028",
  "vol-029",
  "vol-030",
  "vol-031",
  "vol-032",
  "vol-033",
  "vol-034",
  "vol-035",
  "vol-036",
  "vol-037",
  "vol-038",
  "vol-039",
  "vol-040",
  "vol-041",
  "vol-042",
  "vol-043",
  "vol-044",
  "vol-045",
  "vol-046",
  "vol-047",
  "vol-048",
  "vol-049",
  "vol-050",
  "vol-051",
  "vol-052",
  "vol-053",
  "vol-054",
  "vol-055",
  "vol-056",
  "vol-057",
  "vol-058",
  "vol-059",
  "vol-060",
  "vol-061",
  "vol-062",
  "vol-063",
  "vol-064",
  "vol-065",
  "vol-066",
  "vol-067",
  "vol-068",
  "vol-069",
  "vol-070",
  "vol-071",
  "vol-072",
  "vol-073",
  "vol-074",
  "vol-075",
  "vol-076",
  "vol-077",
  "vol-078",
  "vol-079",
  "vol-080",
  "vol-081",
  "vol-082",
  "vol-083",
  "vol-084",
  "vol-085",
  "vol-086-pt1",
  "vol-086-pt2",
  "vol-087-pt1",
  "vol-087-pt2",
  "vol-087-pt3",
  "vol-088",
  "vol-089",
  "vol-090",
  "vol-091",
  "vol-092",
  "vol-093",
  "vol-094",
  "vol-095",
  "vol-096",
  "vol-097",
  "vol-098",
  "vol-099",
  "vol-100",
  "vol-101",
  "vol-102",
  "vol-103",
  "vol-104",
  "vol-105",
  "vol-106",
  "vol-107",
  "vol-108",
  "vol-109",
  "vol-110",
  "vol-111",
  "vol-112",
  "vol-113",
  "vol-114",
  "vol-115",
  "vol-116",
  "vol-117",
  "vol-118",
  "vol-119",
  "vol-120",
];

export interface PermanentRedirect {
  source: string;
  destination: string;
  permanent: true;
}

/**
 * Renamed author ids (`patristica/data/authors.csv`, #82): old id → new id.
 * Author ids are URLs (`/authors/{id}`, `/works?author={id}`), so when one is
 * renamed (or merged into another), add it here; `next.config.ts` redirects
 * the old author page and `parseViewState` maps the old facet value.
 */
export const RENAMED_AUTHOR_IDS: ReadonlyArray<readonly [from: string, to: string]> = [];

/** The current id of an author id from an old link. */
export function currentAuthorId(
  authorId: string,
  renamed: ReadonlyArray<readonly [string, string]> = RENAMED_AUTHOR_IDS,
): string {
  return renamed.find(([from]) => from === authorId)?.[1] ?? authorId;
}

/** Author page redirects for `RENAMED_AUTHOR_IDS`, in `next.config.ts` form. */
export function legacyAuthorRedirects(
  renamed: ReadonlyArray<readonly [string, string]> = RENAMED_AUTHOR_IDS,
): PermanentRedirect[] {
  return renamed.map(([from, to]) => ({
    source: `/authors/${from}`,
    destination: `/authors/${to}`,
    permanent: true as const,
  }));
}

/**
 * Search moved from `/search` to `/`, and the library index from `/` to
 * `/works`. A redirect keeps the query, so old search links still work; an
 * old library link (`/?author=…`) opens search with the same filters.
 */
export function legacyPageRedirects(): PermanentRedirect[] {
  return [{ source: "/search", destination: "/", permanent: true }];
}

/**
 * Reader redirects for `RENAMED_ID_PREFIXES`, `RENAMED_WORK_IDS` and
 * `SPLIT_OGPG_VOLUMES`, in `next.config.ts` form. An old id under a renamed
 * prefix that is also a renamed work takes two hops.
 */
export function legacyWorkRedirects(): PermanentRedirect[] {
  const renamed = RENAMED_ID_PREFIXES.map(([from, to]) => ({
    source: `/works/${from}/:rest+`,
    destination: to ? `/works/${to}/:rest+` : "/works/:rest+",
    permanent: true as const,
  }));
  const works = RENAMED_WORK_IDS.map(([from, to]) => ({
    source: `/works/${from}`,
    destination: `/works/${to}`,
    permanent: true as const,
  }));
  const split = SPLIT_OGPG_VOLUMES.map((vol) => ({
    source: `/works/ogpg/${vol}`,
    destination: `/works?q=ogpg/${vol}/`,
    permanent: true as const,
  }));
  return [...renamed, ...works, ...split];
}
