// Parallel reading (#181): a work and other versions of it side by side, in
// rows built from passage alignment groups, so the same passage starts at the
// same height in every column.
//
// URL: `/works/{lead}?with={other}&with=…#ref`. The leading version gives the
// sections, the table of contents and the element ids (`#ref`); the others
// are columns beside it, in `with` order.
//
// Rows: every version is a list of units (the chunks of its work file). An
// alignment group is one contiguous span of units per version (n:m). Each
// group the leading version shares with another column is an *anchor* row,
// in the leading version's order. A column's groups must also stay in the
// column's own order, so where a column reorders passages (a moved block),
// only its longest run of anchors in order is placed (longest increasing
// subsequence) and the rest is treated as unaligned. Every unit no anchor
// holds gets its own row, with empty cells beside it, right after the anchor
// that precedes it in its own version.

import { alignedMember, MIN_CONFIDENCE, type AlignedMember } from "./alignment";
import type { AlignmentFile, LibraryIndex, WorkFile, WorkRow } from "./library";
import { hasAlignment, workHref } from "./library";
import type { ChunkRole, Section } from "./render";
import { NO_HIGHLIGHT_PARAM } from "./useHashTarget";
import { orgRef, type Position } from "./versions";

/** Query parameter naming each other version read alongside the work. */
export const WITH_PARAM = "with";

/** Versions shown side by side at most, the leading one included. */
export const MAX_VERSIONS = 4;

/** The `with` ids of a reader URL's query, in order, without repeats or the work itself. */
export function parallelIds(params: Pick<URLSearchParams, "getAll">, leadId: string): string[] {
  return [...new Set(params.getAll(WITH_PARAM))].filter((id) => id && id !== leadId);
}

/** Reader URL for `lead` with `others` beside it (the plain reader URL when there are none). */
export function parallelHref(lead: string, others: readonly string[]): string {
  const query = new URLSearchParams(others.map((id) => [WITH_PARAM, id]));
  const q = query.toString();
  return q ? `${workHref(lead)}?${q}` : workHref(lead);
}

/**
 * `href` opened at `position`: `#ref` for a highlighted passage, with
 * `nohl` added to the query for a scroll position (useHashTarget).
 */
export function withPosition(href: string, position: Position | null): string {
  if (!position) return href;
  const query = position.highlight ? "" : `${href.includes("?") ? "&" : "?"}${NO_HIGHLIGHT_PARAM}`;
  return `${href}${query}#${encodeURIComponent(position.ref)}`;
}

/** Why a `with` id isn't shown. */
export type SkipReason = "unknown" | "not-a-version" | "too-many";

export interface ParallelVersions {
  /** The versions to show, the leading one first. */
  columns: WorkRow[];
  skipped: { id: string; reason: SkipReason }[];
}

/**
 * The versions a parallel URL names: the leading work, then each `with` id
 * that is another member of its version group, up to MAX_VERSIONS in all.
 */
export function parallelVersions(index: LibraryIndex, lead: WorkRow, ids: readonly string[]): ParallelVersions {
  const columns = [lead];
  const skipped: ParallelVersions["skipped"] = [];
  for (const id of ids) {
    const row = index.works.find((w) => w.id === id);
    if (!row) skipped.push({ id, reason: "unknown" });
    else if (!lead.version_group || row.version_group !== lead.version_group) skipped.push({ id, reason: "not-a-version" });
    else if (columns.length >= MAX_VERSIONS) skipped.push({ id, reason: "too-many" });
    else columns.push(row);
  }
  return { columns, skipped };
}

/** True if `row` is a Scripture book, whose versions align by versification. */
export function isScriptureBook(row: WorkRow): boolean {
  return Boolean(row.version_group?.startsWith("book:"));
}

/**
 * True if `row`'s versions can be read side by side: a Scripture book, or a
 * work whose version group has an alignment file (none in a library
 * published before alignments were exported).
 */
export function canReadInParallel(index: LibraryIndex, row: WorkRow): boolean {
  return isScriptureBook(row) || hasAlignment(index, row.version_group);
}

// --- Alignment groups per column ---------------------------------------------

function memberFromGroups(groupOf: number[]): AlignedMember {
  const spans = new Map<number, [number, number]>();
  groupOf.forEach((g, u) => {
    if (g < 0) return;
    const span = spans.get(g);
    if (span) span[1] = u + 1;
    else spans.set(g, [u, u + 1]);
  });
  return { groupOf, spans, conf: new Map([...spans.keys()].map((g) => [g, 9])) };
}

/**
 * Scripture books: one group per verse in org versification (BHS /
 * Nestle-Aland, the export's `org_refs`), so KJV Ps 23:1 and the Vulgate's
 * Ps 22:1 share a row. Verses that map to the same org verse form one span
 * (n:m). A work file without `org_refs` (an older library) is read as org
 * numbering, as in the version switcher. A verse whose org ref already
 * occurred earlier in the same version, not just before it, is left
 * unaligned, so spans stay contiguous.
 */
export function versificationMembers(works: readonly WorkFile[]): AlignedMember[] {
  const ids = new Map<string, number>();
  return works.map((work) => {
    const prefix = work.ref_prefix ? `${work.ref_prefix}.` : "";
    const done = new Set<number>();
    let prev = -1;
    const groupOf = work.chunks.map(([suffix]) => {
      const ref = `${prefix}${suffix}`;
      const key = orgRef(work, ref) ?? ref;
      let g = ids.get(key);
      if (g === undefined) ids.set(key, (g = ids.size));
      if (g !== prev && done.has(g)) return -1;
      if (g !== prev && prev >= 0) done.add(prev);
      prev = g;
      return g;
    });
    return memberFromGroups(groupOf);
  });
}

/**
 * The columns' members in a version group's alignment file: null for a
 * version the file leaves out or whose work file no longer has the units the
 * file counts.
 */
export function alignmentMembers(file: AlignmentFile, columns: readonly WorkRow[], works: readonly WorkFile[]): (AlignedMember | null)[] {
  return columns.map((row, c) => {
    const m = alignedMember(file, row.id);
    return m && m.groupOf.length === works[c].chunks.length ? m : null;
  });
}

// --- Rows --------------------------------------------------------------------

/** A column's units in a row: [first, last + 1). */
export type Span = [number, number];

export interface Row {
  /** Stable React key. */
  key: string;
  /** Per column: its units in this row, or null for an empty cell. */
  cells: (Span | null)[];
  /** Per column: true where the version's span in the row's group is below MIN_CONFIDENCE. */
  uncertain: boolean[];
}

/**
 * Indices of a longest strictly increasing subsequence of `values`
 * (patience sorting, O(n log n)).
 */
export function longestIncreasing(values: readonly number[]): Set<number> {
  const tails: number[] = []; // index into values of the smallest tail of each length
  const prev: number[] = new Array(values.length).fill(-1);
  values.forEach((v, i) => {
    let lo = 0;
    let hi = tails.length;
    while (lo < hi) {
      const mid = (lo + hi) >> 1;
      if (values[tails[mid]] < v) lo = mid + 1;
      else hi = mid;
    }
    if (lo > 0) prev[i] = tails[lo - 1];
    tails[lo] = i;
  });
  const out = new Set<number>();
  for (let i = tails.length ? tails[tails.length - 1] : -1; i >= 0; i = prev[i]) out.add(i);
  return out;
}

/** Rows for the columns' `members` (column 0 leads); see the top of this file. */
export function buildRows(members: readonly AlignedMember[]): Row[] {
  const n = members.length;
  const lead = members[0];
  if (!lead) return [];
  const empty = (): (Span | null)[] => new Array(n).fill(null);

  // Anchors: the leading version's groups that another column has, in its order.
  const anchorOf = new Map<number, number>();
  const anchorGroups: number[] = [];
  for (const g of lead.spans.keys()) {
    if (members.some((m, c) => c > 0 && m.spans.has(g))) {
      anchorOf.set(g, anchorGroups.length);
      anchorGroups.push(g);
    }
  }
  const anchors: Row[] = anchorGroups.map((g) => {
    const cells = empty();
    cells[0] = lead.spans.get(g)!;
    return { key: `a${g}`, cells, uncertain: new Array(n).fill(false) };
  });

  // Each column keeps the longest run of anchors that is in its own order too.
  const kept: Set<number>[] = members.map((m, c) => {
    if (c === 0) return new Set(anchorGroups);
    const groups = [...m.spans.keys()].filter((g) => anchorOf.has(g));
    const keep = longestIncreasing(groups.map((g) => anchorOf.get(g)!));
    return new Set(groups.filter((_, i) => keep.has(i)));
  });
  members.forEach((m, c) => {
    if (c === 0) return;
    for (const g of kept[c]) anchors[anchorOf.get(g)!].cells[c] = m.spans.get(g)!;
  });
  // A passage is marked uncertain where it is beside another version and its span is flagged.
  anchors.forEach((row, k) => {
    const g = anchorGroups[k];
    if (row.cells.filter(Boolean).length < 2) return;
    row.uncertain = row.cells.map((cell, c) => cell !== null && (members[c].conf.get(g) ?? 0) < MIN_CONFIDENCE);
  });

  // Everything else: a row per unit (or per group a column has alone), after
  // the anchor before it in its own version.
  // Versions that share a group the leading one lacks (a psalm title the KJV
  // folds into verse 1) share its row when they fall in the same gap.
  const gaps: Row[][] = Array.from({ length: anchors.length + 1 }, () => []);
  const shared: Map<number, Row>[] = gaps.map(() => new Map());
  members.forEach((m, c) => {
    let k = -1;
    for (let u = 0; u < m.groupOf.length; ) {
      const g = m.groupOf[u];
      const span: Span = g >= 0 ? m.spans.get(g)! : [u, u + 1];
      if (g >= 0 && kept[c].has(g)) {
        k = anchorOf.get(g)!;
      } else {
        const existing = g >= 0 ? shared[k + 1].get(g) : undefined;
        if (existing && existing.cells[c] === null) {
          existing.cells[c] = span;
        } else {
          const cells = empty();
          cells[c] = span;
          const row = { key: `u${c}.${span[0]}`, cells, uncertain: new Array(n).fill(false) };
          gaps[k + 1].push(row);
          if (g >= 0 && !existing) shared[k + 1].set(g, row);
        }
      }
      u = span[1];
    }
  });

  const rows: Row[] = [...gaps[0]];
  anchors.forEach((row, k) => {
    rows.push(row);
    for (const gap of gaps[k + 1]) rows.push(gap);
  });
  return rows;
}

// --- Sections ----------------------------------------------------------------

export interface Block {
  /** The leading version's section. */
  section: Section;
  rows: Row[];
  /**
   * Per row: ids of later sections that start inside it (an alignment group
   * that crosses a section boundary), so the table of contents still finds them.
   */
  starts: string[][];
}

/**
 * Rows grouped by the leading version's sections: a row belongs to the
 * section of its first leading unit; a row without one stays with the row
 * before it (rows before the first leading unit go with the first section).
 */
export function sectionBlocks(rows: readonly Row[], sections: readonly Section[], roles: readonly (ChunkRole | undefined)[]): Block[] {
  const blocks: Block[] = [];
  let current: Block | null = null;
  let pending: Row[] = [];
  // The last section that has an element: a block, or an anchor in a row.
  let seen = -1;
  for (const row of rows) {
    const lead = row.cells[0];
    let s: number | undefined;
    const starts: string[] = [];
    let first = true;
    for (let u = lead?.[0] ?? 0; lead && u < lead[1]; u++) {
      const r = roles[u];
      if (!r) continue;
      if (r.sectionIndex > seen) {
        // The row opens a section if it starts with it, else the section starts inside the row.
        if (first) s = r.sectionIndex;
        else starts.push(sections[r.sectionIndex].id);
        seen = r.sectionIndex;
      }
      first = false;
    }
    if (s !== undefined) {
      current = { section: sections[s], rows: [...pending], starts: pending.map(() => []) };
      pending = [];
      blocks.push(current);
    }
    if (current) {
      current.rows.push(row);
      current.starts.push(starts);
    } else {
      pending.push(row);
    }
  }
  if (pending.length && sections[0]) blocks.push({ section: sections[0], rows: pending, starts: pending.map(() => []) });
  return blocks;
}
