import { describe, expect, it } from "vitest";

import { filterAuthors, pseudonymsOf, worksByLanguage } from "./authors";
import { workCounts } from "./filter";
import { authorMap, workAuthors } from "./library";
import { person, workRow } from "./testFixtures";

const authors = authorMap({
  authors: [
    person({ id: "john-chrysostom", name: "John Chrysostom", aliases: ["Joannes Chrysostomus"] }),
    person({ id: "pseudo-chrysostom", name: "Pseudo-Chrysostom", pseudo_of: "john-chrysostom" }),
    person({ id: "jerome", name: "Jerome", aliases: ["Hieronymus"] }),
    person({ id: "dionysius-areopagite", name: "Dionysius the Areopagite" }),
  ],
});

const rows = [
  workRow({ id: "b", author_ids: ["john-chrysostom"], title: "Homiliae in Matthaeum", language: "grc" }),
  workRow({ id: "a", author_ids: ["john-chrysostom"], title: "De sacerdotio", language: "grc" }),
  workRow({ id: "c", author_ids: ["john-chrysostom"], title: "Homilies on Matthew", language: "eng" }),
  workRow({ id: "d", author_ids: ["john-chrysostom", "jerome"], title: "Catena", language: "lat" }),
  workRow({ id: "e", author_ids: ["pseudo-chrysostom"], title: "Opus imperfectum", language: "lat" }),
  workRow({ id: "f", author_ids: [], title: "Anonymous hymn", language: "syc" }),
];

describe("worksByLanguage", () => {
  it("groups an author's works by language name, sorted by title", () => {
    const groups = worksByLanguage(rows, "john-chrysostom");
    expect(groups.map((g) => [g.language, g.works.map((w) => w.id)])).toEqual([
      ["eng", ["c"]],
      ["grc", ["a", "b"]],
      ["lat", ["d"]],
    ]);
  });

  it("lists a multi-author work under each author, and not pseudonymous works", () => {
    expect(worksByLanguage(rows, "jerome").map((g) => g.works.map((w) => w.id))).toEqual([["d"]]);
    expect(worksByLanguage(rows, "dionysius-areopagite")).toEqual([]);
  });
});

describe("pseudonymsOf", () => {
  it("finds the pseudonymous authors that carry a name", () => {
    expect(pseudonymsOf(authors, "john-chrysostom").map((a) => a.id)).toEqual(["pseudo-chrysostom"]);
    expect(pseudonymsOf(authors, "jerome")).toEqual([]);
  });
});

describe("filterAuthors", () => {
  const counts = workCounts(rows);

  it("lists authors with works by name, matching names and aliases folded", () => {
    expect(filterAuthors(authors, counts, "").map((a) => a.id)).toEqual([
      "jerome",
      "john-chrysostom",
      "pseudo-chrysostom",
    ]);
    expect(filterAuthors(authors, counts, "hieronymus").map((a) => a.id)).toEqual(["jerome"]);
    expect(filterAuthors(authors, counts, "CHRYSÓSTOM").map((a) => a.id)).toEqual([
      "john-chrysostom",
      "pseudo-chrysostom",
    ]);
  });

  it("includes authors without works on request", () => {
    expect(filterAuthors(authors, counts, "dionysius", true).map((a) => a.id)).toEqual([
      "dionysius-areopagite",
    ]);
  });
});

describe("workAuthors", () => {
  it("gives display names and ids in order", () => {
    expect(workAuthors(rows[3], authors)).toEqual([
      { id: "john-chrysostom", name: "John Chrysostom" },
      { id: "jerome", name: "Jerome" },
    ]);
  });

  it("gives no authors for an anonymous work, whatever the source string", () => {
    expect(workAuthors(workRow({ author: "Acta Thomae", author_ids: [] }), authors)).toEqual([]);
  });

  it("falls back to the source string, unlinked, for an id missing from the index", () => {
    const row = workRow({ author: "Gelasius", author_ids: ["gelasius-unknown"] });
    expect(workAuthors(row, authors)).toEqual([{ id: null, name: "Gelasius" }]);
  });
});
