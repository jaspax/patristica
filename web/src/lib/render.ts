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

import type { WorkFile } from "./library";

export interface Unit {
  /** Unit number for display (the last ref segment, leading zeros dropped). */
  n: string;
  ref: string;
  text: string;
  outOfPeriod: boolean;
  /** Short all-caps line in a liturgical text: a speaker or rubric label. */
  rubric: boolean;
}

export interface Section {
  /** Unique anchor id. */
  id: string;
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

function samePath(a: string[], b: string[]): boolean {
  return a.length === b.length && a.every((s, i) => s === b[i]);
}

export function parseWork(work: WorkFile, genre: string, sourceId = ""): Section[] {
  const sections: Section[] = [];
  const ids = new Map<string, number>();
  const liturgical = genre === "liturgical";
  const zeroIsTitle = (liturgical || genre === "scripture") && !ZERO_BASED_SOURCES.has(sourceId);
  let current: Section | null = null;

  const open = (path: string[], title: string | null): Section => {
    const base = `s-${path.join(".") || "text"}`;
    const seen = ids.get(base) ?? 0;
    ids.set(base, seen + 1);
    const section: Section = {
      id: seen ? `${base}-${seen + 1}` : base,
      path,
      title,
      label: sectionLabel(path, genre),
      depth: 0,
      units: [],
    };
    sections.push(section);
    return section;
  };

  for (let i = 0; i < work.chunks.length; i++) {
    const [suffix, text, oop] = work.chunks[i];
    const segments = suffix.split(".");
    const next = work.chunks[i + 1]?.[0];
    if (next !== undefined && next.startsWith(`${suffix}.`)) {
      current = open(segments, text.trim());
      continue;
    }
    const path = segments.slice(0, -1);
    const last = segments[segments.length - 1];
    if (current === null || !samePath(current.path, path)) {
      if (zeroIsTitle && /^0+$/.test(last)) {
        current = open(path, text.trim());
        continue;
      }
      current = open(path, null);
    }
    current.units.push({
      n: displaySegment(last),
      ref: work.ref_prefix ? `${work.ref_prefix}.${suffix}` : suffix,
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
