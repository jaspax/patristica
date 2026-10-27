import { describe, expect, it } from "vitest";

import { editorialSegments } from "./editorial";

describe("editorialSegments", () => {
  it("returns the whole text as one plain segment without spans", () => {
    expect(editorialSegments("ⲁⲩⲱ ⲁϥ")).toEqual([{ text: "ⲁⲩⲱ ⲁϥ", kind: null }]);
    expect(editorialSegments("ⲁⲩⲱ ⲁϥ", [])).toEqual([{ text: "ⲁⲩⲱ ⲁϥ", kind: null }]);
  });

  it("cuts the text into plain and editorial segments that join back to it", () => {
    const text = "ⲁⲩⲱ […] ⲁϥ [..]";
    const segments = editorialSegments(text, [
      [4, 7, "lacuna"],
      [11, 15, "lacuna"],
    ]);
    expect(segments).toEqual([
      { text: "ⲁⲩⲱ ", kind: null },
      { text: "[…]", kind: "lacuna" },
      { text: " ⲁϥ ", kind: null },
      { text: "[..]", kind: "lacuna" },
    ]);
    expect(segments.map((s) => s.text).join("")).toBe(text);
  });

  it("marks a whole unit", () => {
    expect(editorialSegments("A Psalm of David.", [[0, 17, "title"]])).toEqual([
      { text: "A Psalm of David.", kind: "title" },
    ]);
  });

  it("uses UTF-16 offsets, as the export writes them", () => {
    // Gothic letters are outside the BMP: two code units each.
    const text = "𐌰𐌱 [...] 𐌲";
    expect(editorialSegments(text, [[5, 10, "lacuna"]])[1]).toEqual({ text: "[...]", kind: "lacuna" });
  });

  it("never loses text to bad spans", () => {
    const text = "abc def";
    for (const spans of [
      [[5, 3, "note"]],
      [[2, 99, "note"]],
      [
        [0, 4, "note"],
        [2, 6, "note"],
      ],
    ] as [number, number, string][][]) {
      expect(editorialSegments(text, spans).map((s) => s.text).join("")).toBe(text);
    }
  });
});
