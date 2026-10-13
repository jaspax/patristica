/**
 * Permanent redirects for work ids that have been renamed or split.
 *
 * Work ids appear in reader URLs (`/works/{work_id}`), so renaming a source
 * breaks links to its works. Each entry maps an old id prefix to its new one;
 * `next.config.ts` turns them into `redirects`.
 */
export const RENAMED_ID_PREFIXES: ReadonlyArray<readonly [from: string, to: string]> = [
  // #52: every Coptic Scriptorium work is patristic, not liturgical.
  ["liturgical/coptic-scriptorium", "patristic/coptic-scriptorium"],
];

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
  "vol-120",
];

export interface PermanentRedirect {
  source: string;
  destination: string;
  permanent: true;
}

/** Reader redirects for `RENAMED_ID_PREFIXES` and `SPLIT_OGPG_VOLUMES`, in `next.config.ts` form. */
export function legacyWorkRedirects(): PermanentRedirect[] {
  const renamed = RENAMED_ID_PREFIXES.map(([from, to]) => ({
    source: `/works/${from}/:rest+`,
    destination: `/works/${to}/:rest+`,
    permanent: true as const,
  }));
  const split = SPLIT_OGPG_VOLUMES.map((vol) => ({
    source: `/works/ogpg/${vol}`,
    destination: `/?q=ogpg/${vol}/`,
    permanent: true as const,
  }));
  return [...renamed, ...split];
}
