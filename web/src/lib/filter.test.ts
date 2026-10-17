import { describe, expect, it } from "vitest";

import {
  DEFAULT_VIEW,
  filterWorks,
  fold,
  parseViewState,
  sortWorks,
  viewStateToParams,
  type ViewState,
} from "./filter";
import type { WorkRow } from "./library";

function row(overrides: Partial<WorkRow>): WorkRow {
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

const sources = { pta: "Patristic Text Archive", kjv: "King James Version" };

const rows = [
  row({ id: "a", author: "Augustinus", title: "Confessiones", date: 397, date_range: [397, 400] }),
  row({ id: "b", author: "Ἰωάννης Χρυσόστομος", title: "Homiliae", language: "grc", date: 390 }),
  row({ id: "c", title: "Genesis", genre: "scripture", source_id: "kjv", language: "eng", date: -500 }),
  row({ id: "d", author: "Basilius", title: "Epistulae" }),
];

const view = (overrides: Partial<ViewState>): ViewState => ({ ...DEFAULT_VIEW, ...overrides });
const ids = (list: WorkRow[]) => list.map((r) => r.id);

describe("fold", () => {
  it("ignores case and diacritics", () => {
    expect(fold("Ἰωάννης")).toBe("ιωαννης");
    expect(fold("BASÍLIUS")).toBe("basilius");
  });
});

describe("filterWorks", () => {
  it("matches every query term against author, title and collection", () => {
    expect(ids(filterWorks(rows, view({ q: "augustin" }), sources))).toEqual(["a"]);
    expect(ids(filterWorks(rows, view({ q: "ιωαννης homil" }), sources))).toEqual(["b"]);
    expect(ids(filterWorks(rows, view({ q: "king james" }), sources))).toEqual(["c"]);
    expect(ids(filterWorks(rows, view({ q: "augustin homil" }), sources))).toEqual([]);
  });

  it("filters by facets", () => {
    expect(ids(filterWorks(rows, view({ language: "grc" }), sources))).toEqual(["b"]);
    expect(ids(filterWorks(rows, view({ genre: "scripture" }), sources))).toEqual(["c"]);
    expect(ids(filterWorks(rows, view({ source: "pta" }), sources))).toEqual(["a", "b", "d"]);
  });

  it("filters by overlapping date range and drops undated works", () => {
    expect(ids(filterWorks(rows, view({ from: 395 }), sources))).toEqual(["a"]);
    expect(ids(filterWorks(rows, view({ to: 0 }), sources))).toEqual(["c"]);
    expect(ids(filterWorks(rows, view({ from: 380, to: 398 }), sources))).toEqual(["a", "b"]);
  });
});

describe("sortWorks", () => {
  it("sorts missing values last in both directions", () => {
    expect(ids(sortWorks(rows, "author", "asc", sources))).toEqual(["a", "d", "b", "c"]);
    expect(ids(sortWorks(rows, "author", "desc", sources))).toEqual(["b", "d", "a", "c"]);
    expect(ids(sortWorks(rows, "date", "asc", sources))).toEqual(["c", "b", "a", "d"]);
    expect(ids(sortWorks(rows, "date", "desc", sources))).toEqual(["a", "b", "c", "d"]);
  });

  it("sorts by collection label", () => {
    expect(ids(sortWorks(rows, "source", "asc", sources))[0]).toBe("c");
  });

  it("does not mutate its input", () => {
    const copy = [...rows];
    sortWorks(rows, "title", "asc", sources);
    expect(rows).toEqual(copy);
  });
});

describe("view state in the URL", () => {
  it("round-trips non-default values", () => {
    const state = view({ q: "basil", language: "grc", from: -100, to: 500, sort: "date", dir: "desc" });
    const params = viewStateToParams(state);
    expect(params.toString()).toBe("q=basil&language=grc&from=-100&to=500&sort=date&dir=desc");
    expect(parseViewState(params)).toEqual(state);
  });

  it("omits defaults and ignores invalid values", () => {
    expect(viewStateToParams(DEFAULT_VIEW).toString()).toBe("");
    expect(parseViewState(new URLSearchParams("sort=bogus&dir=sideways&from=abc"))).toEqual(
      DEFAULT_VIEW,
    );
  });

  it("maps a source id from before #102 to its current id (#70)", () => {
    expect(parseViewState(new URLSearchParams("source=scripture/kjv")).source).toBe("kjv");
    expect(parseViewState(new URLSearchParams("source=liturgical/coptic-scriptorium")).source).toBe(
      "coptic-scriptorium",
    );
    expect(parseViewState(new URLSearchParams("source=councils/ecumenical")).source).toBe("ecumenical");
    expect(parseViewState(new URLSearchParams("source=pta")).source).toBe("pta");
  });
});
