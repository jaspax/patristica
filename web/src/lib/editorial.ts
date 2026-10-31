// Editorial material in a chunk's text (#236): titles, supplements, lacunae,
// metadata and notes that an editor or the source added. It stays in the text
// for readers but is left out of embedding and translation. The library export
// gives it as spans over the chunk text (`WorkFile.editorial`).

import type { EditorialSpan } from "./library";

/** The kind of editorial span that marks a liturgical rubric (#500). */
export const RUBRIC_KIND = "rubric";

/** A run of a chunk's text: plain, or editorial material of `kind`. */
export interface TextSegment {
  text: string;
  kind: string | null;
}

/**
 * `text` cut into plain and editorial segments, in order; joined, they give
 * `text` back. Spans that are empty, out of order, overlap an earlier span or
 * run past the text are clipped or ignored, so a stale export can't lose text.
 */
export function editorialSegments(text: string, spans?: readonly EditorialSpan[]): TextSegment[] {
  if (!spans || spans.length === 0) return [{ text, kind: null }];
  const out: TextSegment[] = [];
  let pos = 0;
  for (const [rawStart, rawEnd, kind] of spans) {
    const start = Math.max(pos, Math.min(rawStart, text.length));
    const end = Math.min(rawEnd, text.length);
    if (end <= start) continue;
    if (start > pos) out.push({ text: text.slice(pos, start), kind: null });
    out.push({ text: text.slice(start, end), kind });
    pos = end;
  }
  if (pos < text.length) out.push({ text: text.slice(pos), kind: null });
  return out;
}
