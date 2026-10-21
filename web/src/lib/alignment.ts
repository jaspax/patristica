// Passage alignments in the reader (#179, #181): decode a version group's
// alignment file (lib/library.ts AlignmentFile) into per-unit groups, the
// same reading as patristica/alignment_store.py.
//
// A unit is a chunk of the work file, in file order: derived verses
// (`ref.sN`) and heading chunks are units too. An alignment group is one
// contiguous span of units per member (n:m). A member's span in a group is
// used only at MIN_CONFIDENCE or more; below it the group is "flagged".

import type { AlignmentFile, AlignmentMember, WorkFile } from "./library";

/** A member's span in a group counts only at this confidence (tenths): alignment_store.MIN_CONFIDENCE. */
export const MIN_CONFIDENCE = 5;

/** A member of an alignment file, decoded. */
export interface AlignedMember {
  /** Per unit: its group, or -1 for none. */
  groupOf: number[];
  /** Group → confidence in tenths (0–9). */
  conf: Map<number, number>;
  /** Group → [first unit, last unit + 1). */
  spans: Map<number, [number, number]>;
}

const TOKEN = /\.|=|[+-]\d*/y;

/** Inverse of alignment_store.encode_spans; null if malformed. */
export function decodeSpans(spans: string): number[] | null {
  const out: number[] = [];
  let last = -1;
  let prev = -1;
  TOKEN.lastIndex = 0;
  while (TOKEN.lastIndex < spans.length) {
    const m = TOKEN.exec(spans);
    if (!m) return null;
    const tok = m[0];
    let g: number;
    if (tok === ".") g = -1;
    else if (tok === "=") {
      if (prev < 0) return null;
      g = prev;
    } else {
      const d = tok.length > 1 ? Number(tok.slice(1)) : 1;
      g = tok[0] === "+" ? last + d : last - d;
      if (g < 0) return null;
      last = g;
    }
    out.push(g);
    prev = g;
  }
  return out;
}

/** Decode one member; null if its spans are malformed or don't match its unit and confidence counts. */
export function decodeMember(member: AlignmentMember): AlignedMember | null {
  const groupOf = decodeSpans(member.spans);
  if (!groupOf || groupOf.length !== member.units) return null;
  const spans = new Map<number, [number, number]>();
  groupOf.forEach((g, u) => {
    if (g < 0) return;
    const span = spans.get(g);
    if (span) span[1] = u + 1;
    else spans.set(g, [u, u + 1]);
  });
  // Confidence digits follow the groups' first appearance, which is the spans map's insertion order.
  const order = [...spans.keys()];
  if (member.conf.length !== order.length) return null;
  const conf = new Map(order.map((g, i) => [g, Number(member.conf[i])]));
  return { groupOf, conf, spans };
}

const decoded = new WeakMap<AlignmentFile, Map<string, AlignedMember | null>>();

/**
 * The decoded member `workId` of `file`, or null when the file has no (valid)
 * row for it. Decoded once per file.
 */
export function alignedMember(file: AlignmentFile, workId: string): AlignedMember | null {
  let members = decoded.get(file);
  if (!members) decoded.set(file, (members = new Map()));
  if (!members.has(workId)) {
    const raw = file.members[workId];
    members.set(workId, raw ? decodeMember(raw) : null);
  }
  return members.get(workId)!;
}

/** True if `member`'s span in group `g` is confident enough to use. */
export function confident(member: AlignedMember, g: number): boolean {
  return (member.conf.get(g) ?? 0) >= MIN_CONFIDENCE;
}

function joinRef(prefix: string, suffix: string): string {
  return [prefix, suffix].filter(Boolean).join(".");
}

/** The full ref of unit `u` of a work file. */
export function unitRef(work: WorkFile, u: number): string {
  return joinRef(work.ref_prefix, work.chunks[u][0]);
}

/**
 * The unit of `work` that `ref` names: the chunk with that ref, else (for a
 * paragraph split into derived verses, whose element carries the source
 * unit's ref) its first derived verse. -1 if none.
 */
export function unitIndex(work: WorkFile, ref: string): number {
  const prefix = work.ref_prefix ? `${work.ref_prefix}.` : "";
  if (prefix && !ref.startsWith(prefix)) return -1;
  const suffix = ref.slice(prefix.length);
  const exact = work.chunks.findIndex(([s]) => s === suffix);
  if (exact >= 0) return exact;
  return work.chunks.findIndex(([s]) => s.startsWith(`${suffix}.s`) && /^s\d+$/.test(s.slice(suffix.length + 1)));
}

/** Where `from`'s unit lands in `to`. */
export interface AlignedUnit {
  /** The first unit of the target's span. */
  unit: number;
  /** False when the source unit itself has no usable group and an earlier unit's was used. */
  exact: boolean;
}

/**
 * The unit of `to` at which to open the passage that unit `u` of `from` is
 * in: the first unit of `to`'s span in the same alignment group, if both
 * spans are confident. Otherwise the nearest preceding unit of `from` whose
 * group both have is used (not exact); null when there is none.
 */
export function alignUnit(from: AlignedMember, to: AlignedMember, u: number): AlignedUnit | null {
  for (let i = Math.min(u, from.groupOf.length - 1); i >= 0; i--) {
    const g = from.groupOf[i];
    if (g < 0 || !confident(from, g) || !confident(to, g)) continue;
    const span = to.spans.get(g);
    if (span) return { unit: span[0], exact: i === u };
  }
  return null;
}
