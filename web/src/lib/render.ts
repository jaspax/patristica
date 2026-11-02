// Turn a work's normalized chunks into readable structure: sections with
// headings, and numbered units (verses or paragraphs) inside them.
//
// Refs are dot-separated paths (`Gen.1.1`, `Letter.1.3`). The last segment is
// the unit number and the segments before it are the section path. A chunk
// whose ref is the parent of the next chunk's ref (`Canon.1` followed by
// `Canon.1.1`) is a heading: it opens a section and its text is the title.
// When the source marks every heading (`marks_headings`: a heading is a chunk
// that is a `title` or `heading` editorial span as a whole, #128), the marks
// decide instead: such a chunk is
// a heading, and an unmarked chunk at a division level is the division's lead
// paragraph (body text before its subdivisions), not a heading.
// In liturgical texts and scripture, so is a unit numbered zero at the start
// of a section (`0002.0000` in the liturgies, psalm superscriptions). Sources
// such as Coptic Scriptorium number ordinary sentences from zero, even in
// their liturgical works (the Lament of the Virgin, #103).
//
// A ref ending in `sN` (`3.2.s1`, `3.2.s2`) is a derived verse: a piece of the
// source's unit `3.2`, cut by the pipeline so search can point at a passage
// about a verse long (patristica/versify.py). The derived verses of one
// source unit are rendered together as that unit, each with its own anchor.
//
// Editorial material (titles, supplements, lacunae, metadata that an editor or
// the source added, #236) stays in the text: `editorial` on a unit or a
// derived verse says which parts of its text it is (`EditorialText` shows them).

import { RUBRIC_KIND } from "./editorial";
import type { EditorialSpan, WorkFile } from "./library";

/** A derived verse: a piece of a source unit cut by the pipeline. */
export interface Part {
  /** Derived verse number within its unit ("3" for `….s3`). */
  n: string;
  ref: string;
  text: string;
  /** Editorial material in `text`. */
  editorial?: EditorialSpan[];
}

export interface Unit {
  /** Unit number for display (the last ref segment, leading zeros dropped). */
  n: string;
  ref: string;
  text: string;
  /** The unit's derived verses, if the pipeline split it; their texts make up `text`. */
  parts?: Part[];
  /** Editorial material in `text` (a unit with `parts` has it on each part instead). */
  editorial?: EditorialSpan[];
  outOfPeriod: boolean;
  /**
   * A rubric as a whole: marked so in the data (every word in a `rubric`
   * editorial span, #500), or, in a liturgical text with no marks, a short
   * all-caps line (a speaker or rubric label).
   */
  rubric: boolean;
}

export interface Section {
  /** Unique anchor id. */
  id: string;
  /** Ref of the heading chunk the title comes from (an anchor too, for search results). */
  ref: string | null;
  /**
   * For a section with no heading chunk, the ref its path names (`Did.1` for
   * units `Did.1.1`, `Did.1.2`, …), an anchor on its heading: a link to a unit
   * that was later cut into numbered verses still opens there (#122). Null on
   * a repeat of the path and for the top level.
   */
  anchor: string | null;
  path: string[];
  /** Heading text taken from the source, if the source has a heading chunk. */
  title: string | null;
  /** Editorial material in `title` (offsets into the trimmed title). */
  titleEditorial?: EditorialSpan[];
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

/** Every non-space character of `text` is in a span of one of `kinds`. */
function isMarkedAs(text: string, spans: readonly EditorialSpan[] | undefined, kinds: ReadonlySet<string>): boolean {
  if (!spans || spans.length === 0 || text.trim() === "") return false;
  let pos = 0;
  for (const [start, end, kind] of spans) {
    if (!kinds.has(kind)) continue;
    if (text.slice(pos, start).trim() !== "") return false;
    pos = Math.max(pos, end);
  }
  return text.slice(pos).trim() === "";
}

/** Every non-space character of `text` is in a `rubric` span. */
export function isMarkedRubric(text: string, spans?: readonly EditorialSpan[]): boolean {
  return isMarkedAs(text, spans, RUBRIC_KINDS);
}

const RUBRIC_KINDS: ReadonlySet<string> = new Set([RUBRIC_KIND]);
/** Editorial kinds of a heading: a chunk in these as a whole is one (#128). */
export const HEADING_KINDS: ReadonlySet<string> = new Set(["title", "heading"]);

/** A chunk that is a title or heading as a whole, as the source marked it (#128). */
export function isMarkedHeading(text: string, spans?: readonly EditorialSpan[]): boolean {
  return isMarkedAs(text, spans, HEADING_KINDS);
}

/**
 * Is this unit a rubric as a whole? Marks in the data decide when the work
 * has any (the source said what its rubrics are); otherwise, in a liturgical
 * text, the all-caps heuristic.
 */
function unitIsRubric(text: string, spans: readonly EditorialSpan[] | undefined, workMarksRubrics: boolean, liturgical: boolean): boolean {
  if (workMarksRubrics) return isMarkedRubric(text, spans);
  return liturgical && isRubric(text);
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

/**
 * A heading chunk's text trimmed for a title, with its editorial spans moved
 * onto the trimmed text (clipped to it; spans left with nothing are dropped).
 */
export function trimmedTitle(
  text: string,
  spans?: readonly EditorialSpan[],
): { title: string; editorial?: EditorialSpan[] } {
  const title = text.trim();
  if (!spans || spans.length === 0) return { title };
  const lead = text.length - text.trimStart().length;
  const editorial: EditorialSpan[] = [];
  for (const [s, e, kind] of spans) {
    const start = Math.max(0, s - lead);
    const end = Math.min(title.length, e - lead);
    if (end > start) editorial.push([start, end, kind]);
  }
  return editorial.length ? { title, editorial } : { title };
}

export function parseWork(work: WorkFile, genre: string, sourceId = ""): Section[] {
  const sections: Section[] = [];
  const ids = new Map<string, number>();
  const liturgical = genre === "liturgical";
  const marksRubrics = Object.values(work.editorial ?? {}).some((spans) => spans.some((s) => s[2] === RUBRIC_KIND));
  // A work whose source marks every heading (#128): the marks say which chunks
  // are headings, and a chunk at a division level that isn't one is body text.
  const marksHeadings = work.marks_headings === true;
  const zeroIsTitle = (liturgical || genre === "scripture") && !ZERO_BASED_SOURCES.has(sourceId);
  let current: Section | null = null;

  const open = (path: string[], title: string | null, ref: string | null = null): Section => {
    const base = `s-${path.join(".") || "text"}`;
    const seen = ids.get(base) ?? 0;
    ids.set(base, seen + 1);
    const section: Section = {
      id: seen ? `${base}-${seen + 1}` : base,
      ref,
      anchor: ref === null && !seen && path.length > 0 ? joinRef(work.ref_prefix, path.join(".")) : null,
      path,
      title,
      label: sectionLabel(path, genre),
      depth: 0,
      units: [],
    };
    sections.push(section);
    return section;
  };

  const makeUnit = (n: string, suffix: string, text: string, oop: number | undefined): Unit => {
    const unit: Unit = {
      n,
      ref: joinRef(work.ref_prefix, suffix),
      text,
      outOfPeriod: oop === 1,
      rubric: unitIsRubric(text, work.editorial?.[suffix], marksRubrics, liturgical),
    };
    const marks = work.editorial?.[suffix];
    if (marks) unit.editorial = marks;
    return unit;
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
      const marks = work.editorial?.[suffix];
      if (marks) part.editorial = marks;
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
    const heading = (path: string[]): Section => {
      const { title, editorial } = trimmedTitle(text, work.editorial?.[suffix]);
      const section = open(path, title, joinRef(work.ref_prefix, suffix));
      if (editorial) section.titleEditorial = editorial;
      return section;
    };
    const parent = next !== undefined && next.startsWith(`${suffix}.`);
    if (marksHeadings) {
      if (isMarkedHeading(text, work.editorial?.[suffix])) {
        // A heading of its division, or (when nothing follows inside it) of
        // the text that follows at its own level.
        current = heading(parent ? segments : segments.slice(0, -1));
        continue;
      }
      if (parent) {
        // Body text that sits in a division before its subdivisions: the
        // division's lead paragraph, under the division's label.
        if (current === null || !samePath(current.path, segments)) current = open(segments, null);
        current.units.push(makeUnit("", suffix, text, oop));
        continue;
      }
    } else if (parent) {
      current = heading(segments);
      continue;
    }
    const path = segments.slice(0, -1);
    const last = segments[segments.length - 1];
    if (current === null || !samePath(current.path, path)) {
      if (zeroIsTitle && /^0+$/.test(last)) {
        current = heading(path);
        continue;
      }
      current = open(path, null);
    }
    current.units.push(makeUnit(displaySegment(last), suffix, text, oop));
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
