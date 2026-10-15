// Display formatting for work metadata.

import type { WorkRow } from "./library";

/** -500 → "500 BC", 397 → "397". */
export function formatYear(year: number): string {
  return year < 0 ? `${-year} BC` : String(year);
}

/** Short date for tables: "c. 397", "397", or "" when undated. */
export function formatDate(row: Pick<WorkRow, "date" | "date_confidence">): string {
  if (row.date === null) return "";
  const prefix = row.date_confidence === "established" ? "" : "c. ";
  return prefix + formatYear(row.date);
}

/** Full date for the reader header, with range and confidence. */
export function formatDateLong(
  row: Pick<WorkRow, "date" | "date_range" | "date_confidence">,
): string {
  const parts: string[] = [];
  if (row.date !== null) parts.push(formatYear(row.date));
  const [lo, hi] = row.date_range ?? [null, null];
  if (lo !== null && hi !== null && lo !== hi) {
    parts.push(`(${formatYear(lo)}–${formatYear(hi)})`);
  }
  if (parts.length === 0) return "Undated";
  return `${parts.join(" ")}, ${row.date_confidence}`;
}

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
