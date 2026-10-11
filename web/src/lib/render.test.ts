import { describe, expect, it } from "vitest";

import type { ChunkRow, WorkFile } from "./library";
import { displaySegment, isRubric, parseWork } from "./render";

function work(ref_prefix: string, chunks: ChunkRow[]): WorkFile {
  return { work_id: "test/work", ref_prefix, chunks };
}

describe("parseWork", () => {
  it("groups scripture verses into chapters", () => {
    const sections = parseWork(
      work("Gen", [
        ["1.1", "In the beginning"],
        ["1.2", "And the earth"],
        ["2.1", "Thus the heavens"],
      ]),
      "scripture",
    );
    expect(sections.map((s) => [s.id, s.label, s.units.map((u) => u.n)])).toEqual([
      ["s-1", "Chapter 1", ["1", "2"]],
      ["s-2", "Chapter 2", ["1"]],
    ]);
    expect(sections[0].units[0].ref).toBe("Gen.1.1");
  });

  it("treats a parent ref as the section's heading", () => {
    const sections = parseWork(
      work("Ancyra.Canon", [
        ["1", "Canon I"],
        ["1.1", "Those presbyters…"],
        ["1.2", "Notes"],
        ["2", "Canon II"],
        ["2.1", "Deacons likewise…"],
      ]),
      "council",
    );
    expect(sections.map((s) => [s.title, s.units.length])).toEqual([
      ["Canon I", 2],
      ["Canon II", 1],
    ]);
  });

  it("nests headings by depth", () => {
    const sections = parseWork(
      work("tlg4102", [
        ["tlg006", "Work title"],
        ["tlg006.toc", "Contents"],
        ["tlg006.toc.1", "Chapter one"],
        ["tlg006.1.1", "First paragraph"],
      ]),
      "patristic",
    );
    expect(sections.map((s) => [s.title ?? s.label, s.depth, s.units.length])).toEqual([
      ["Work title", 0, 0],
      ["Contents", 1, 1],
      ["tlg006.1", 1, 1],
    ]);
  });

  it("gives flat works a single unlabelled section", () => {
    const sections = parseWork(
      work("tlg2035.tlg130", [
        ["1", "1. Αἱ μὲν αἱρέσεις"],
        ["2", "2. Τί γὰρ ὅμοιον"],
      ]),
      "patristic",
    );
    expect(sections).toHaveLength(1);
    expect(sections[0].label).toBeNull();
    expect(sections[0].units.map((u) => u.n)).toEqual(["1", "2"]);
  });

  it("uses a zero-numbered first unit as the section title", () => {
    const sections = parseWork(
      work("ByzLit.Chrysostom", [
        ["0001.0000", "ΛΕΙΤΟΥΡΓΙΑ"],
        ["0002.0000", "ΕΝΑΡΞΙΣ"],
        ["0002.0001", "ΔΙΑΚΟΝΟΣ"],
      ]),
      "liturgical",
    );
    expect(sections.map((s) => [s.title, s.units.length])).toEqual([
      ["ΛΕΙΤΟΥΡΓΙΑ", 0],
      ["ΕΝΑΡΞΙΣ", 1],
    ]);
  });

  it("keeps zero-numbered units in prose", () => {
    const [section] = parseWork(work("CopScr.abraham", [["000.0000", "ϭⲟⲗ"], ["000.0001", "ⲛⲉⲛⲧ"]]), "patristic");
    expect(section.title).toBeNull();
    expect(section.units.map((u) => u.n)).toEqual(["0", "1"]);
  });

  it("drops leading zeros and marks rubrics and out-of-period chunks", () => {
    const sections = parseWork(
      work("ByzLit.Chrysostom", [
        ["0002.0001", "ΔΙΑΚΟΝΟΣ"],
        ["0002.0002", "Εὐλόγησον, Δέσποτα."],
        ["0002.0003", "Later addition", 1],
      ]),
      "liturgical",
    );
    const [section] = sections;
    expect(section.units.map((u) => [u.n, u.rubric, u.outOfPeriod])).toEqual([
      ["1", true, false],
      ["2", false, false],
      ["3", false, true],
    ]);
  });

  it("only marks rubrics in liturgical texts", () => {
    const [section] = parseWork(work("X", [["1", "CAPUT PRIMUM"]]), "patristic");
    expect(section.units[0].rubric).toBe(false);
  });

  it("makes anchor ids unique when a section path repeats", () => {
    const sections = parseWork(
      work("X", [
        ["1.1", "a"],
        ["2.1", "b"],
        ["1.2", "c"],
      ]),
      "patristic",
    );
    expect(sections.map((s) => s.id)).toEqual(["s-1", "s-2", "s-1-2"]);
  });
});

describe("isRubric", () => {
  it("accepts short upper-case lines", () => {
    expect(isRubric("ΙΕΡΕΥΣ")).toBe(true);
    expect(isRubric("THE PRIEST")).toBe(true);
  });

  it("rejects mixed case, long lines and caseless scripts", () => {
    expect(isRubric("Εὐλόγησον, Δέσποτα.")).toBe(false);
    expect(isRubric("A".repeat(41))).toBe(false);
    expect(isRubric("ܫܠܡܐ")).toBe(false);
    expect(isRubric("123")).toBe(false);
  });
});

describe("displaySegment", () => {
  it("strips leading zeros from numbers only", () => {
    expect(displaySegment("0012")).toBe("12");
    expect(displaySegment("0000")).toBe("0");
    expect(displaySegment("iv")).toBe("iv");
  });
});
