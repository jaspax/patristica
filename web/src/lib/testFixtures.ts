// Fixtures shared by the Vitest suites (not used by the app).

import type { Author, WorkRow } from "./library";

/** An index row with defaults for every field. */
export function workRow(overrides: Partial<WorkRow>): WorkRow {
  return {
    id: "x/y",
    author: null,
    author_ids: [],
    title: "Untitled",
    language: "lat",
    genre: "patristic",
    tradition: null,
    date: null,
    date_range: null,
    date_confidence: "uncertain",
    source_id: "pta",
    edition: null,
    license: "unknown",
    provenance_url: null,
    translation_of: null,
    chunks: 1,
    file: "works/x/y.json",
    ...overrides,
  };
}

/** An authors.json record with defaults for every field but id and name. */
export function person(overrides: Partial<Author> & Pick<Author, "id" | "name">): Author {
  return {
    aliases: [],
    birth: null,
    death: null,
    floruit: null,
    tradition: null,
    external_ids: [],
    pseudo_of: null,
    ...overrides,
  };
}
