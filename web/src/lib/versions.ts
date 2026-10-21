// Other versions of a work (#144): the members of its version group
// (patristica/versions.py, #178), which one is the original, and where to open
// another version so the reader keeps its place.

import { alignedMember, alignUnit, unitIndex, unitRef } from "./alignment";
import { languageInfo } from "./lang";
import type { AlignmentFile, LibraryIndex, WorkFile, WorkRow } from "./library";
import { fragmentId, NO_HIGHLIGHT_PARAM, TARGET_ATTRIBUTE } from "./useHashTarget";

/**
 * Every work in `row`'s version group, `row` included, in index order; [] when
 * the work has no other version. Group ids can change when links are added,
 * so they are only compared here, never shown or put in URLs.
 */
export function versionMembers(index: LibraryIndex, row: WorkRow): WorkRow[] {
  if (!row.version_group) return [];
  return index.works.filter((w) => w.version_group === row.version_group);
}

/** Number of works in each version group, for "N versions" labels. */
export function versionCounts(works: readonly WorkRow[]): Map<string, number> {
  const counts = new Map<string, number>();
  for (const w of works) {
    if (w.version_group) counts.set(w.version_group, (counts.get(w.version_group) ?? 0) + 1);
  }
  return counts;
}

/**
 * Languages in which a text was most likely first written, best first: used
 * only when no `translation_of` link in the group says which version is the
 * original. Hebrew first for the Old Testament, then Greek (New Testament,
 * deuterocanon and most Fathers). English is never the original.
 */
export const ORIGINAL_LANGUAGE_ORDER: readonly string[] = ["hbo", "grc", "syc", "lat", "cop", "hye", "gez", "got"];

/**
 * The ids of the group's originals: the versions the others translate.
 *
 * 1. If any member's `translation_of` names another member, follow those links
 *    to the end of each chain (Coptic → Greek → Hebrew); the original language
 *    is the language of the works they end at.
 * 2. Otherwise the original language is the first of ORIGINAL_LANGUAGE_ORDER
 *    the group has (Hebrew for Genesis, Greek for Matthew).
 *
 * The originals are the members in the original language that are not
 * themselves translations, so every edition of the original text is marked.
 * A group in a single language (editions of one text) has no original.
 */
export function originalIds(members: readonly WorkRow[]): Set<string> {
  const byId = new Map(members.map((m) => [m.id, m]));
  const languages = new Set(members.map((m) => m.language));
  if (languages.size < 2) return new Set();

  const rootLanguages = new Set<string>();
  for (const m of members) {
    let work = m.translation_of ? byId.get(m.translation_of) : undefined;
    if (!work) continue;
    const seen = new Set([m.id]);
    while (work.translation_of && byId.has(work.translation_of) && !seen.has(work.id)) {
      seen.add(work.id);
      work = byId.get(work.translation_of)!;
    }
    rootLanguages.add(work.language);
  }
  if (rootLanguages.size === 0) {
    const first = ORIGINAL_LANGUAGE_ORDER.find((l) => languages.has(l));
    if (first) rootLanguages.add(first);
  }
  return new Set(
    members.filter((m) => !m.translation_of && rootLanguages.has(m.language)).map((m) => m.id),
  );
}

export interface LanguageGroup {
  /** Corpus language code. */
  language: string;
  /** English display name. */
  name: string;
  works: WorkRow[];
}

/**
 * Versions grouped by language: the originals' language first, then by
 * language name; within a language, originals first, then by collection label
 * and title.
 */
export function groupByLanguage(
  works: readonly WorkRow[],
  originals: ReadonlySet<string>,
  sources: Record<string, string>,
): LanguageGroup[] {
  const groups = new Map<string, WorkRow[]>();
  for (const w of works) groups.set(w.language, [...(groups.get(w.language) ?? []), w]);
  const hasOriginal = (ws: WorkRow[]) => ws.some((w) => originals.has(w.id));
  const label = (w: WorkRow) => sources[w.source_id] ?? w.source_id;
  return [...groups.entries()]
    .map(([language, ws]) => ({
      language,
      name: languageInfo(language).name,
      works: ws.sort(
        (a, b) =>
          Number(originals.has(b.id)) - Number(originals.has(a.id)) ||
          label(a).localeCompare(label(b)) ||
          a.title.localeCompare(b.title),
      ),
    }))
    .sort((a, b) => Number(hasOriginal(b.works)) - Number(hasOriginal(a.works)) || a.name.localeCompare(b.name));
}

/** What a version list entry shows beside its language and collection label. */
export interface VersionDetails {
  /** The version's title, when it differs from the current work's (a partial version, a sibling). */
  title: string | null;
  /** The edition, only when language, collection and title would leave two entries identical. */
  edition: string | null;
}

/**
 * The details that tell the other versions apart (`works` excludes `current`).
 * An entry is its language and collection label; the title is added when it
 * differs from the current work's, and the edition only for entries that
 * would otherwise look the same (ANF vol. 1 and vol. 9 of one letter).
 */
export function distinguishVersions(
  works: readonly WorkRow[],
  current: WorkRow,
  sources: Record<string, string>,
): Map<string, VersionDetails> {
  const title = (w: WorkRow) => (w.title !== current.title ? w.title : null);
  const key = (w: WorkRow) => [w.language, sources[w.source_id] ?? w.source_id, title(w) ?? ""].join("\u0000");
  const seen = new Map<string, number>();
  for (const w of works) seen.set(key(w), (seen.get(key(w)) ?? 0) + 1);
  return new Map(
    works.map((w) => [w.id, { title: title(w), edition: seen.get(key(w))! > 1 ? w.edition : null }]),
  );
}

// --- Keeping the reader's place ----------------------------------------------

function joinRef(prefix: string, suffix: string): string {
  return [prefix, suffix].filter(Boolean).join(".");
}

function parentRef(ref: string): string {
  return ref.slice(0, Math.max(ref.lastIndexOf("."), 0));
}

/**
 * A Scripture ref in org versification (BHS / Nestle-Aland), the numbering
 * every Scripture version maps onto (patristica/versification.py): the
 * export's `org_refs` for refs that differ, otherwise the ref itself. Null for
 * a work that isn't a versified Scripture book.
 */
export function orgRef(work: WorkFile, ref: string): string | null {
  if (!work.org_refs) return null;
  const prefix = work.ref_prefix ? `${work.ref_prefix}.` : "";
  const suffix = ref.startsWith(prefix) ? ref.slice(prefix.length) : ref;
  return work.org_refs[suffix] ?? ref;
}

/**
 * The ref in `work`'s own numbering of the verse at org ref `org`: the first
 * chunk that maps to it, else the first chunk of the same org chapter, else
 * null (also for a work that isn't a versified Scripture book).
 */
export function nativeRef(work: WorkFile, org: string): string | null {
  if (!work.org_refs) return null;
  const chapter = parentRef(org);
  let inChapter: string | null = null;
  for (const [suffix] of work.chunks) {
    const ref = joinRef(work.ref_prefix, suffix);
    const mapped = work.org_refs[suffix] ?? ref;
    if (mapped === org) return ref;
    if (inChapter === null && chapter && parentRef(mapped) === chapter) inChapter = ref;
  }
  return inChapter;
}

/** Where the reader is, and which version it is switching to. */
export interface PositionRequest {
  from: WorkRow;
  fromWork: WorkFile;
  /** The ref the reader is at in `from` (a chunk ref; may be a derived verse). */
  ref: string;
  to: WorkRow;
  /** Load the target's work file (cached: the reader reuses it). */
  loadTarget: () => Promise<WorkFile>;
  /**
   * Load the passage alignment of the version group (#179); absent when the
   * library has none for it (or predates alignments).
   */
  loadAlignment?: () => Promise<AlignmentFile>;
}

/** A target ref that is near the reader's passage rather than the passage itself. */
export interface ApproximateRef {
  ref: string;
  approximate: true;
}

/**
 * Finds the passage in `to` that corresponds to `ref` in `from`. Returns the
 * target ref (or an ApproximateRef for a nearby passage), null when it
 * applies but finds no passage, or undefined when it doesn't apply to this
 * pair, so the next mapper is tried.
 */
export type PositionMapper = (req: PositionRequest) => Promise<string | ApproximateRef | null | undefined>;

/** Scripture: native ref → org ref → the target's native ref. */
export const scripturePosition: PositionMapper = async ({ from, fromWork, ref, to, loadTarget }) => {
  // Two Scripture books of one book group. A work file without org_refs (a
  // library published before #144, or a stale cache) is read as already in
  // org numbering: the same ref, else the same chapter, beats the top.
  const sameBook = Boolean(from.version_group?.startsWith("book:")) && from.version_group === to.version_group;
  const org = fromWork.org_refs ? orgRef(fromWork, ref) : sameBook ? ref : null;
  if (org === null) return undefined;
  const target = await loadTarget();
  if (target.org_refs) return nativeRef(target, org);
  return sameBook ? nativeRef({ ...target, org_refs: {} }, org) : undefined;
};

/**
 * Passage alignment (#179), for every other work: the reader's unit → its
 * alignment group → the first unit of the target's span in that group. A
 * unit in no group, or in one whose span is below MIN_CONFIDENCE in either
 * version, falls back to the nearest preceding unit that has one
 * (approximate), else the top. Doesn't apply when the group has no alignment
 * file or either version has no row in it (left out as stale), and gives the
 * top when a work file doesn't have the units its row counts (a stale cache).
 */
export const alignmentPosition: PositionMapper = async ({ from, fromWork, ref, to, loadTarget, loadAlignment }) => {
  if (!loadAlignment || !from.version_group || from.version_group !== to.version_group) return undefined;
  // A failed load (a library without the file yet) is the same as no alignment.
  const file = await loadAlignment().catch(() => null);
  if (!file) return undefined;
  const source = alignedMember(file, from.id);
  const target = alignedMember(file, to.id);
  if (!source || !target) return undefined;
  if (source.groupOf.length !== fromWork.chunks.length) return null;
  const u = unitIndex(fromWork, ref);
  if (u < 0) return null;
  const found = alignUnit(source, target, u);
  if (!found) return null;
  const toWork = await loadTarget();
  if (target.groupOf.length !== toWork.chunks.length) return null;
  const targetRef = unitRef(toWork, found.unit);
  return found.exact ? targetRef : { ref: targetRef, approximate: true };
};

/**
 * Mappers tried in order: Scripture's versification (exact and complete for
 * a Scripture book), then passage alignment for every other work.
 */
export const POSITION_MAPPERS: readonly PositionMapper[] = [scripturePosition, alignmentPosition];

/** Where to open the target: a ref, and whether it is only near the reader's passage. */
export interface MappedPosition {
  ref: string;
  approximate: boolean;
}

/** The passage to open in `req.to`, or null to open it at the top. */
export async function mapPosition(
  req: PositionRequest,
  mappers: readonly PositionMapper[] = POSITION_MAPPERS,
): Promise<MappedPosition | null> {
  for (const mapper of mappers) {
    const found = await mapper(req);
    if (found === undefined) continue;
    if (found === null) return null;
    return typeof found === "string" ? { ref: found, approximate: false } : found;
  }
  return null;
}

/** Where the reader is: a passage, and whether it is highlighted (a fragment the reader chose). */
export interface Position {
  ref: string;
  /** The URL fragment's highlighted passage (a search result, a verse link), not just the scroll position. */
  highlight: boolean;
}

/**
 * Where the reader is in the text inside `container`: the URL fragment's
 * passage while it is on screen (highlighted if useHashTarget marked it), else
 * the first passage at least partly visible at the top of the viewport (not
 * highlighted). Null while the top of the text is still in view (the reader
 * hasn't started reading: open the other version at its top too).
 */
export function currentPosition(container: HTMLElement | null, hash: string): Position | null {
  if (!container) return null;
  const height = window.innerHeight;
  const target = fragmentId(hash);
  const marked = target ? document.getElementById(target) : null;
  if (marked && container.contains(marked)) {
    const box = marked.getBoundingClientRect();
    if (box.bottom > 0 && box.top < height) {
      return { ref: target, highlight: marked.hasAttribute(TARGET_ATTRIBUTE) };
    }
  }
  if (container.getBoundingClientRect().top >= 0) return null;
  // Look inside the first section on screen only: off-screen sections skip
  // layout (content-visibility), and measuring their contents would force it.
  for (const section of container.querySelectorAll("section")) {
    if (section.getBoundingClientRect().bottom <= 0) continue;
    for (const el of section.querySelectorAll("[id]")) {
      if (el.getBoundingClientRect().bottom > 0) return { ref: el.id, highlight: false };
    }
    return null;
  }
  return null;
}

/**
 * What follows a reader path to open a position: `#ref` for a highlighted
 * passage, `?nohl#ref` for one taken from the scroll position (scrolled to but
 * not highlighted, useHashTarget), "" for the top.
 */
export function positionSuffix(position: Position | null): string {
  if (!position) return "";
  return `${position.highlight ? "" : `?${NO_HIGHLIGHT_PARAM}`}#${encodeURIComponent(position.ref)}`;
}
