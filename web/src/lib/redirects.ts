/**
 * Permanent redirects for work ids that have been renamed.
 *
 * Work ids appear in reader URLs (`/works/{work_id}`), so renaming a source
 * breaks links to its works. Each entry maps an old id prefix to its new one;
 * `next.config.ts` turns them into `redirects`.
 */
export const RENAMED_ID_PREFIXES: ReadonlyArray<readonly [from: string, to: string]> = [
  // #52: every Coptic Scriptorium work is patristic, not liturgical.
  ["liturgical/coptic-scriptorium", "patristic/coptic-scriptorium"],
];

export interface PermanentRedirect {
  source: string;
  destination: string;
  permanent: true;
}

/** Reader redirects for `RENAMED_ID_PREFIXES`, in `next.config.ts` form. */
export function legacyWorkRedirects(): PermanentRedirect[] {
  return RENAMED_ID_PREFIXES.map(([from, to]) => ({
    source: `/works/${from}/:rest+`,
    destination: `/works/${to}/:rest+`,
    permanent: true,
  }));
}

