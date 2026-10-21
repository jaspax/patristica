// Turn a work's normalized chunks into readable structure: sections with
// headings, and numbered units (verses or paragraphs) inside them.
//
// Refs are dot-separated paths (`Gen.1.1`, `Letter.1.3`). The last segment is
// the unit number and the segments before it are the section path. A chunk
// whose ref is the parent of the next chunk's ref (`Canon.1` followed by
// `Canon.1.1`) is a heading: it opens a section and its text is the title.
// In liturgical texts and scripture, so is a unit numbered zero at the start
// of a section (`0002.0000` in the liturgies, psalm superscriptions). Sources
// such as Coptic Scriptorium number ordinary sentences from zero, even in
// their liturgical works (the Lament of the Virgin, #103).
//
// A ref ending in `sN` (`3.2.s1`, `3.2.s2`) is a derived verse: a piece of the
// source's unit `3.2`, cut by the pipeline so search can point at a passage
// about a verse long (patristica/versify.py). The derived verses of one
// source unit are rendered together as that unit, each with its own anchor.

import type { WorkFile } from "./library";

/** A derived verse: a piece of a source unit cut by the pipeline. */
export interface Part {
  /** Derived verse number within its unit ("3" for `….s3`). */
  n: string;
  ref: string;
  text: string;
}

export interface Unit {
  /** Unit number for display (the last ref segment, leading zeros dropped). */
  n: string;
  ref: string;
  text: string;
  /** The unit's derived verses, if the pipeline split it; their texts make up `text`. */
  parts?: Part[];
  outOfPeriod: boolean;
  /** Short all-caps line in a liturgical text: a speaker or rubric label. */
  rubric: boolean;
}

export interface Section {
  /** Unique anchor id. */
  id: string;
  /** Ref of the heading chunk the title comes from (an anchor too, for search results). */
  ref: string | null;
  path: string[];
  /** Heading text taken from the source, if the source has a heading chunk. */
  title: string | null;
  /** Fallback heading built from the ref path ("Chapter 3", "2.4"); null for flat works. */
  label: string | null;
  /** Nesting depth for the heading level, 0 = top. */
  depth: number;
  units: Unit[];
}

const RUBRIC_MAX_LENGTH = 40;

/** Short line written entirely in upper case (in a script that has case). */
export function isRubric(text: string): boolean {
  const t = text.trim();
  return (
    t.length > 0 &&
    t.length <= RUBRIC_MAX_LENGTH &&
    t === t.toUpperCase() &&
    t !== t.toLowerCase()
  );
}

/** "0012" → "12"; non-numeric segments are unchanged. */
export function displaySegment(segment: string): string {
  return /^\d+$/.test(segment) ? String(Number(segment)) : segment;
}

/** Sources whose units are numbered from zero, so a zero unit is ordinary text. */
const ZERO_BASED_SOURCES: ReadonlySet<string> = new Set(["coptic-scriptorium"]);

function sectionLabel(path: string[], genre: string): string | null {
  if (path.length === 0) return null;
  const shown = path.map(displaySegment);
  if (genre === "scripture" && path.length === 1) return `Chapter ${shown[0]}`;
  return shown.join(".");
}

const DERIVED = /^s(\d+)$/;

/** True if a ref names a derived verse rather than a unit of the source. */
export function isDerivedRef(ref: string): boolean {
  return DERIVED.test(ref.slice(ref.lastIndexOf(".") + 1));
}

function joinRef(prefix: string, suffix: string): string {
  return [prefix, suffix].filter(Boolean).join(".");
}

function samePath(a: string[], b: string[]): boolean {
  return a.length === b.length && a.every((s, i) => s === b[i]);
}

export function parseWork(work: WorkFile, genre: string, sourceId = ""): Section[] {
  const sections: Section[] = [];
  const ids = new Map<string, number>();
  const liturgical = genre === "liturgical";
  const zeroIsTitle = (liturgical || genre === "scripture") && !ZERO_BASED_SOURCES.has(sourceId);
  let current: Section | null = null;

  const open = (path: string[], title: string | null, ref: string | null = null): Section => {
    const base = `s-${path.join(".") || "text"}`;
    const seen = ids.get(base) ?? 0;
    ids.set(base, seen + 1);
    const section: Section = {
      id: seen ? `${base}-${seen + 1}` : base,
      ref,
      path,
      title,
      label: sectionLabel(path, genre),
      depth: 0,
      units: [],
    };
    sections.push(section);
    return section;
  };

  const prefixLast = work.ref_prefix.split(".").pop() ?? "";
  let previousBase: string | null = null;

  for (let i = 0; i < work.chunks.length; i++) {
    const [suffix, text, oop] = work.chunks[i];
    const derived = DERIVED.exec(suffix.slice(suffix.lastIndexOf(".") + 1));
    if (derived) {
      const base = suffix.split(".").slice(0, -1);
      const baseRef = joinRef(work.ref_prefix, base.join("."));
      const part: Part = { n: derived[1], ref: joinRef(work.ref_prefix, suffix), text };
      const path = base.slice(0, -1);
      const last = current?.units[current.units.length - 1];
      if (last?.parts && previousBase === baseRef) {
        last.parts.push(part);
        last.text = `${last.text} ${text}`;
        last.outOfPeriod ||= oop === 1;
      } else {
        if (current === null || !samePath(current.path, path)) current = open(path, null);
        current.units.push({
          n: displaySegment(base[base.length - 1] ?? prefixLast),
          ref: baseRef,
          text,
          parts: [part],
          outOfPeriod: oop === 1,
          rubric: false,
        });
      }
      previousBase = baseRef;
      continue;
    }
    previousBase = null;
    const segments = suffix.split(".");
    const next = work.chunks[i + 1]?.[0];
    if (next !== undefined && next.startsWith(`${suffix}.`)) {
      current = open(segments, text.trim(), joinRef(work.ref_prefix, suffix));
      continue;
    }
    const path = segments.slice(0, -1);
    const last = segments[segments.length - 1];
    if (current === null || !samePath(current.path, path)) {
      if (zeroIsTitle && /^0+$/.test(last)) {
        current = open(path, text.trim(), joinRef(work.ref_prefix, suffix));
        continue;
      }
      current = open(path, null);
    }
    current.units.push({
      n: displaySegment(last),
      ref: joinRef(work.ref_prefix, suffix),
      text,
      outOfPeriod: oop === 1,
      rubric: liturgical && isRubric(text),
    });
  }

  // Heading depth relative to the shallowest section path.
  const minDepth = Math.min(...sections.map((s) => s.path.length));
  for (const s of sections) s.depth = s.path.length - minDepth;

  // A work with a single untitled section needs no heading at all.
  if (sections.length === 1 && sections[0].title === null) sections[0].label = null;
  return sections;
}

/** What a chunk of the work file is in the parsed structure. */
export type ChunkRole =
  | { kind: "heading"; section: Section; sectionIndex: number }
  | { kind: "unit"; unit: Unit; sectionIndex: number }
  | { kind: "part"; unit: Unit; part: number; sectionIndex: number };

/**
 * The role of each chunk of `work` (in file order) in `sections`, its
 * parseWork result: the heading of a section, a unit, or one derived verse
 * of a unit. Parallel reading (#181) renders ranges of chunks with it.
 */
export function chunkRoles(work: WorkFile, sections: readonly Section[]): ChunkRole[] {
  const index = new Map(work.chunks.map(([suffix], i) => [joinRef(work.ref_prefix, suffix), i]));
  const roles: ChunkRole[] = new Array(work.chunks.length);
  sections.forEach((section, sectionIndex) => {
    const heading = section.ref === null ? undefined : index.get(section.ref);
    if (heading !== undefined) roles[heading] = { kind: "heading", section, sectionIndex };
    for (const unit of section.units) {
      if (unit.parts) {
        unit.parts.forEach((p, part) => {
          const i = index.get(p.ref);
          if (i !== undefined) roles[i] = { kind: "part", unit, part, sectionIndex };
        });
      } else {
        const i = index.get(unit.ref);
        if (i !== undefined) roles[i] = { kind: "unit", unit, sectionIndex };
      }
    }
  });
  return roles;
}
