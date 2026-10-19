import { describe, expect, it } from "vitest";

import {
  ANONYMOUS,
  authorFacet,
  authorFilterHref,
  DEFAULT_VIEW,
  filterWorks,
  fold,
  parseViewState,
  sortWorks,
  viewStateToParams,
  type ViewState,
} from "./filter";
import { authorMap, type WorkRow } from "./library";
import { person } from "./testFixtures";

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
    version_group: null,
    chunks: 1,
    file: "works/x/y.json",
    ...overrides,
  };
}

const sources = { pta: "Patristic Text Archive", kjv: "King James Version" };

const rows = [
  row({ id: "a", author: "Augustinus", author_ids: ["augustine-of-hippo"], title: "Confessiones", date: 397, date_range: [397, 400] }),
  row({ id: "b", author: "Ἰωάννης Χρυσόστομος", author_ids: ["john-chrysostom"], title: "Homiliae", language: "grc", date: 390 }),
  row({ id: "c", title: "Genesis", genre: "scripture", source_id: "kjv", language: "eng", date: -500 }),
  row({ id: "d", author: "Basilius", author_ids: ["basil-of-caesarea"], title: "Epistulae" }),
];

const authors = authorMap({
  authors: [
    person({ id: "augustine-of-hippo", name: "Augustine of Hippo", aliases: ["Augustinus"] }),
    person({ id: "john-chrysostom", name: "John Chrysostom", aliases: ["Joannes Chrysostomus"] }),
    person({ id: "basil-of-caesarea", name: "Basil of Caesarea", aliases: ["Basilius"] }),
    person({ id: "jerome", name: "Jerome", aliases: ["Hieronymus"] }),
  ],
});

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
    expect(ids(filterWorks(rows, view({ language: ["grc"] }), sources))).toEqual(["b"]);
    expect(ids(filterWorks(rows, view({ genre: ["scripture"] }), sources))).toEqual(["c"]);
    expect(ids(filterWorks(rows, view({ source: "pta" }), sources))).toEqual(["a", "b", "d"]);
  });

  it("matches any of several values of a facet", () => {
    expect(ids(filterWorks(rows, view({ language: ["grc", "eng"] }), sources))).toEqual(["b", "c"]);
    expect(ids(filterWorks(rows, view({ language: ["grc", "eng"], genre: ["scripture"] }), sources))).toEqual([
      "c",
    ]);
  });

  it("filters by overlapping date range and drops undated works", () => {
    expect(ids(filterWorks(rows, view({ from: 395 }), sources))).toEqual(["a"]);
    expect(ids(filterWorks(rows, view({ to: 0 }), sources))).toEqual(["c"]);
    expect(ids(filterWorks(rows, view({ from: 380, to: 398 }), sources))).toEqual(["a", "b"]);
  });
});

describe("sortWorks", () => {
  it("sorts missing values last in both directions", () => {
    expect(ids(sortWorks(rows, "author", "asc", sources, authors))).toEqual(["a", "d", "b", "c"]);
    expect(ids(sortWorks(rows, "author", "desc", sources, authors))).toEqual(["b", "d", "a", "c"]);
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
    const state = view({ q: "basil", language: ["grc"], from: -100, to: 500, sort: "date", dir: "desc" });
    const params = viewStateToParams(state);
    expect(params.toString()).toBe("q=basil&language=grc&from=-100&to=500&sort=date&dir=desc");
    expect(parseViewState(params)).toEqual(state);
  });

  it("writes several values as repeated parameters, and reads comma-separated ones too", () => {
    const state = view({ language: ["grc", "lat"], genre: ["patristic"] });
    expect(viewStateToParams(state).toString()).toBe("language=grc&language=lat&genre=patristic");
    expect(parseViewState(viewStateToParams(state))).toEqual(state);
    expect(parseViewState(new URLSearchParams("language=grc,lat&language=lat&genre=patristic"))).toEqual(state);
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

describe("authors (#145)", () => {
  const jerome = row({ id: "e", author: "Jerome, Saint", author_ids: ["jerome"], title: "De viris illustribus" });
  // A multi-author volume counts under each of its authors.
  const both = row({
    id: "f",
    author: "Hieronymus; Augustinus",
    author_ids: ["jerome", "augustine-of-hippo"],
    title: "Epistulae mutuae",
  });
  // The source names a work title as author; it resolves to no author.
  const titled = row({ id: "g", author: "Acta Thomae", title: "Acts of Thomas" });
  const all = [...rows, jerome, both, titled];

  it("matches the text query against author names and aliases, folded", () => {
    expect(ids(filterWorks(all, view({ q: "Hieronymus" }), sources, authors))).toEqual(["e", "f"]);
    expect(ids(filterWorks(all, view({ q: "jerome" }), sources, authors))).toEqual(["e", "f"]);
    expect(ids(filterWorks(all, view({ q: "Chrysostomus" }), sources, authors))).toEqual(["b"]);
    expect(ids(filterWorks(all, view({ q: "CHRYSÓSTOM" }), sources, authors))).toEqual(["b"]);
    expect(ids(filterWorks(all, view({ q: "augustine" }), sources, authors))).toEqual(["a", "f"]);
    // Without the author index only the source's string matches.
    expect(ids(filterWorks(all, view({ q: "Chrysostomus" }), sources))).toEqual([]);
  });

  it("filters by author id, and ANONYMOUS selects works without authors", () => {
    expect(ids(filterWorks(all, view({ author: ["jerome"] }), sources, authors))).toEqual(["e", "f"]);
    expect(ids(filterWorks(all, view({ author: ["augustine-of-hippo"] }), sources, authors))).toEqual([
      "a",
      "f",
    ]);
    expect(ids(filterWorks(all, view({ author: [ANONYMOUS] }), sources, authors))).toEqual(["c", "g"]);
  });

  it("matches a work by any of several authors", () => {
    expect(ids(filterWorks(all, view({ author: ["jerome", ANONYMOUS] }), sources, authors))).toEqual([
      "c",
      "e",
      "f",
      "g",
    ]);
  });

  it("counts works per author id in the facet, Anonymous first, then by name", () => {
    expect(authorFacet(all, authors)).toEqual([
      { id: ANONYMOUS, name: "Anonymous", count: 2 },
      { id: "augustine-of-hippo", name: "Augustine of Hippo", count: 2 },
      { id: "basil-of-caesarea", name: "Basil of Caesarea", count: 1 },
      { id: "jerome", name: "Jerome", count: 2 },
      { id: "john-chrysostom", name: "John Chrysostom", count: 1 },
    ]);
  });

  it("leaves Anonymous out of the facet when every work has an author", () => {
    expect(authorFacet([jerome], authors)).toEqual([{ id: "jerome", name: "Jerome", count: 1 }]);
  });

  it("sorts by display name, so source spellings don't scatter an author", () => {
    // "Jerome, Saint" and "Hieronymus; …" both sort as Jerome; works without authors go last.
    expect(ids(sortWorks([titled, jerome, both, rows[0]], "author", "asc", sources, authors))).toEqual([
      "a",
      "e",
      "f",
      "g",
    ]);
  });

  it("keeps the author facet in the URL", () => {
    const state = view({ author: ["jerome"] });
    expect(viewStateToParams(state).toString()).toBe("author=jerome");
    expect(parseViewState(new URLSearchParams("author=jerome"))).toEqual(state);
    expect(authorFilterHref("john-chrysostom")).toBe("/works?author=john-chrysostom");
    expect(authorFilterHref(ANONYMOUS)).toBe("/works?author=anonymous");
  });
});
