import { describe, expect, it } from "vitest";

import type { LibraryIndex, WorkRow } from "./library";
import { commonUrlPrefix, summarizeSources } from "./sources";

function row(overrides: Partial<WorkRow>): WorkRow {
  return {
    id: "x",
    author: null,
    title: "T",
    language: "grc",
    genre: "patristic",
    tradition: null,
    date: null,
    date_range: null,
    date_confidence: "uncertain",
    source_id: "pta",
    edition: null,
    license: "cc-by-sa-4.0",
    provenance_url: null,
    translation_of: null,
    chunks: 10,
    file: "works/x.json",
    ...overrides,
  };
}

const index: LibraryIndex = {
  version: "",
  sources: { pta: "Patristic Text Archive", "lxx-rahlfs": "Septuagint (Rahlfs)" },
  works: [
    row({ id: "a", provenance_url: "https://github.com/pta/data/a.xml", edition: "pta-grc1" }),
    row({ id: "b", provenance_url: "https://github.com/pta/data/b.xml", edition: "pta-grc1", license: "cc-by-4.0" }),
    row({ id: "c", provenance_url: "https://github.com/pta/data/c.xml", edition: "pta-syc1" }),
    row({ id: "d", provenance_url: "https://github.com/pta/data/d.xml", chunks: 5 }),
    row({
      id: "e",
      source_id: "lxx-rahlfs",
      license: "cc-by-nc-sa-4.0",
      provenance_url: "https://github.com/eliranwong/LXX-Rahlfs-1935",
    }),
  ],
};

describe("summarizeSources", () => {
  const [pta, lxx] = summarizeSources(index);

  it("groups works by collection, sorted by label", () => {
    expect([pta.label, lxx.label]).toEqual(["Patristic Text Archive", "Septuagint (Rahlfs)"]);
    expect([pta.works, pta.chunks]).toEqual([4, 35]);
  });

  it("counts licences and editions, most common first", () => {
    expect(pta.licenses).toEqual([
      ["cc-by-sa-4.0", 3],
      ["cc-by-4.0", 1],
    ]);
    expect(pta.editions).toEqual(["pta-grc1", "pta-syc1"]);
    expect(pta.moreEditions).toBe(0);
  });

  it("collapses many provenance URLs to their common prefix", () => {
    expect(pta.links).toEqual(["https://github.com/pta/data/"]);
    expect(lxx.links).toEqual(["https://github.com/eliranwong/LXX-Rahlfs-1935"]);
  });

  it("flags non-commercial collections", () => {
    expect(pta.nonCommercial).toBe(false);
    expect(lxx.nonCommercial).toBe(true);
  });
});

describe("commonUrlPrefix", () => {
  it("cuts back to a path boundary", () => {
    expect(commonUrlPrefix(["https://x.org/a/b1", "https://x.org/a/b2"])).toBe("https://x.org/a/");
    expect(commonUrlPrefix(["https://x.org/a", "https://x.org/a"])).toBe("https://x.org/a");
    expect(commonUrlPrefix(["https://a.org/x", "https://b.org/y"])).toBe("");
  });
});
