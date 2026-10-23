// Display formatting for work metadata.

import type { Author, AuthorDate, WorkRow } from "./library";

/** -500 → "500 BC", 397 → "397". */
export function formatYear(year: number): string {
  return year < 0 ? `${-year} BC` : String(year);
}

/** "374–430" (or "430" for a single year), for an author activity range. */
function formatSpan([lo, hi]: [number, number]): string {
  return lo === hi ? formatYear(lo) : `${formatYear(lo)}–${formatYear(hi)}`;
}

/**
 * Short date for tables: "c. 397", "397", or "" when undated. A work dated
 * only by its authors (#151) shows their activity, marked as theirs:
 * "author fl. 374–430".
 */
export function formatDate(
  row: Pick<WorkRow, "date" | "date_confidence" | "author_date_range">,
): string {
  if (row.date === null) {
    return row.author_date_range ? `author fl. ${formatSpan(row.author_date_range)}` : "";
  }
  const prefix = row.date_confidence === "established" ? "" : "c. ";
  return prefix + formatYear(row.date);
}

/** Full date for the reader header, with range and confidence. */
export function formatDateLong(
  row: Pick<WorkRow, "date" | "date_range" | "date_confidence" | "author_date_range">,
): string {
  const parts: string[] = [];
  if (row.date !== null) parts.push(formatYear(row.date));
  const [lo, hi] = row.date_range ?? [null, null];
  if (lo !== null && hi !== null && lo !== hi) {
    parts.push(`(${formatYear(lo)}–${formatYear(hi)})`);
  }
  if (parts.length === 0) {
    return row.author_date_range
      ? `Undated (author active ${formatSpan(row.author_date_range)})`
      : "Undated";
  }
  return `${parts.join(" ")}, ${row.date_confidence}`;
}

/**
 * An author-index date, with its certainty as authors.csv writes it:
 * "354" established, "c. 347" approximate, "350?" uncertain, "340–345" a range.
 */
export function formatAuthorDate(date: AuthorDate): string {
  const years =
    date.low === date.high ? formatYear(date.low) : `${formatYear(date.low)}–${formatYear(date.high)}`;
  if (date.confidence === "approximate") return `c. ${years}`;
  if (date.confidence === "uncertain") return `${years}?`;
  return years;
}

/** Short dates for lists: "354–430", "c. 347–420", "fl. 431–438", or "". */
export function formatLifespan(author: Pick<Author, "birth" | "death" | "floruit">): string {
  const { birth, death, floruit } = author;
  if (birth || death) {
    if (!birth) return `d. ${formatAuthorDate(death!)}`;
    if (!death) return `b. ${formatAuthorDate(birth)}`;
    // A range inside a span would read ambiguously ("340–345–420"), so use "/".
    const part = (d: AuthorDate) => formatAuthorDate(d).replace("–", "/");
    return `${part(birth)} – ${part(death)}`;
  }
  return floruit ? `fl. ${formatAuthorDate(floruit)}` : "";
}

export const TRADITIONS: Record<string, string> = {
  greek: "Greek",
  latin: "Latin",
  syriac: "Syriac",
  ethiopic: "Ethiopic",
  coptic: "Coptic",
  armenian: "Armenian",
  gothic: "Gothic",
  jewish: "Jewish",
};

export const LICENSES: Record<string, { label: string; url?: string }> = {
  public_domain: { label: "Public domain" },
  "cc-by-4.0": { label: "CC BY 4.0", url: "https://creativecommons.org/licenses/by/4.0/" },
  "cc-by-sa-4.0": { label: "CC BY-SA 4.0", url: "https://creativecommons.org/licenses/by-sa/4.0/" },
  "cc-by-nc-4.0": { label: "CC BY-NC 4.0", url: "https://creativecommons.org/licenses/by-nc/4.0/" },
  "cc-by-nc-sa-4.0": {
    label: "CC BY-NC-SA 4.0",
    url: "https://creativecommons.org/licenses/by-nc-sa/4.0/",
  },
  "academic-noncommercial": { label: "Academic, non-commercial use" },
  unknown: { label: "Unknown" },
};

export const GENRES: Record<string, string> = {
  scripture: "Scripture",
  patristic: "Patristic",
  liturgical: "Liturgical",
  council: "Council",
  apocrypha: "Apocrypha",
};
