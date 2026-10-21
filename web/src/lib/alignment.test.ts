import { describe, expect, it } from "vitest";

import { alignedMember, alignUnit, decodeMember, decodeSpans, unitIndex, unitRef } from "./alignment";
import type { AlignmentFile, WorkFile } from "./library";

describe("decodeSpans", () => {
  it("reads the store's tokens (patristica/alignment_store.encode_spans)", () => {
    // encode_spans([0, 1, 1, -1, 4, 2]) == "++=.+3-2"
    expect(decodeSpans("++=.+3-2")).toEqual([0, 1, 1, -1, 4, 2]);
    expect(decodeSpans(".++++")).toEqual([-1, 0, 1, 2, 3]);
    expect(decodeSpans("")).toEqual([]);
  });

  it("rejects malformed spans", () => {
    expect(decodeSpans("=")).toBeNull();
    expect(decodeSpans(".=")).toBeNull();
    expect(decodeSpans("-1")).toBeNull();
    expect(decodeSpans("+x")).toBeNull();
  });
});

describe("decodeMember", () => {
  it("gives each group its span and confidence, in order of first appearance", () => {
    const m = decodeMember({ units: 5, spans: "+=.+2-1", conf: "937" })!;
    expect(m.groupOf).toEqual([0, 0, -1, 2, 1]);
    expect([...m.spans]).toEqual([
      [0, [0, 2]],
      [2, [3, 4]],
      [1, [4, 5]],
    ]);
    expect([...m.conf]).toEqual([
      [0, 9],
      [2, 3],
      [1, 7],
    ]);
  });

  it("rejects a row whose counts don't match", () => {
    expect(decodeMember({ units: 6, spans: "+=.+2-1", conf: "937" })).toBeNull();
    expect(decodeMember({ units: 5, spans: "+=.+2-1", conf: "93" })).toBeNull();
  });
});

describe("alignedMember", () => {
  const file: AlignmentFile = {
    group: "g",
    pivot: "a",
    groups: 1,
    members: { a: { units: 1, spans: "+", conf: "9" }, bad: { units: 2, spans: "+", conf: "9" } },
  };

  it("decodes a member once, and is null for a missing or malformed row", () => {
    expect(alignedMember(file, "a")).toBe(alignedMember(file, "a"));
    expect(alignedMember(file, "bad")).toBeNull();
    expect(alignedMember(file, "nope")).toBeNull();
  });
});

describe("unitIndex and unitRef", () => {
  const work: WorkFile = {
    work_id: "w",
    ref_prefix: "Ep",
    chunks: [
      ["1", "Heading"],
      ["1.1", "a"],
      ["1.2.s1", "b"],
      ["1.2.s2", "c"],
      ["1.20", "d"],
    ],
  };

  it("finds a chunk by its ref, and a split paragraph by its first derived verse", () => {
    expect(unitIndex(work, "Ep.1")).toBe(0);
    expect(unitIndex(work, "Ep.1.2.s2")).toBe(3);
    expect(unitIndex(work, "Ep.1.2")).toBe(2);
    expect(unitIndex(work, "Ep.1.20")).toBe(4);
    expect(unitIndex(work, "Ep.9")).toBe(-1);
    expect(unitIndex(work, "Other.1")).toBe(-1);
    expect(unitIndex(work, "s-1")).toBe(-1);
    expect(unitRef(work, 3)).toBe("Ep.1.2.s2");
  });

  it("finds the first derived verse of a work that is one split paragraph (its ref is the prefix)", () => {
    // render.ts gives the paragraph the ref prefix as its ref (render.test.ts).
    const whole: WorkFile = { work_id: "w", ref_prefix: "Ep.7", chunks: [["s1", "a"], ["s2", "b"]] };
    expect(unitIndex(whole, "Ep.7")).toBe(0);
    expect(unitIndex(whole, "Ep.7.s2")).toBe(1);
    expect(unitIndex(whole, "Ep")).toBe(-1);
  });
});

describe("alignUnit", () => {
  const from = decodeMember({ units: 5, spans: "+=+.+", conf: "939" })!; // groups 0 0 1 . 2
  const to = decodeMember({ units: 4, spans: "++=+", conf: "999" })!; // groups 0 1 1 2

  it("opens at the first unit of the target's span in the same group", () => {
    expect(alignUnit(from, to, 0)).toEqual({ unit: 0, exact: true });
    expect(alignUnit(from, to, 1)).toEqual({ unit: 0, exact: true });
    expect(alignUnit(from, to, 4)).toEqual({ unit: 3, exact: true });
  });

  it("falls back to the nearest preceding unit with a usable group", () => {
    // Unit 2's group is flagged (confidence 3) in `from`, unit 3 is in none.
    expect(alignUnit(from, to, 2)).toEqual({ unit: 0, exact: false });
    expect(alignUnit(from, to, 3)).toEqual({ unit: 0, exact: false });
  });

  it("is null when no earlier unit is aligned", () => {
    const late = decodeMember({ units: 2, spans: ".+", conf: "9" })!;
    expect(alignUnit(late, to, 0)).toBeNull();
  });
});
