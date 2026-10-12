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
  "vol-025",
  "vol-026",
  "vol-027",
  "vol-029",
  "vol-031",
  "vol-032",
  "vol-044",
  "vol-045",
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
