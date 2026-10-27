import { describe, expect, it } from "vitest";

import type { ChunkRow, WorkFile } from "./library";
import { chunkRoles, displaySegment, isDerivedRef, isRubric, parseWork } from "./render";

describe("chunkRoles", () => {
  it("names each chunk's role: a section heading, a unit, or a derived verse of a unit", () => {
    const work: WorkFile = {
      work_id: "w",
      ref_prefix: "Ep",
      chunks: [
        ["1", "Letter One"],
        ["1.1", "Greeting."],
        ["1.2.s1", "First."],
        ["1.2.s2", "Second."],
      ],
    };
    const roles = chunkRoles(work, parseWork(work, "patristic"));
    expect(roles.map((r) => r.kind)).toEqual(["heading", "unit", "part", "part"]);
    expect(roles[0].kind === "heading" && roles[0].section.title).toBe("Letter One");
    expect(roles[3].kind === "part" && [roles[3].unit.ref, roles[3].part]).toEqual(["Ep.1.2", 1]);
    expect(roles.every((r) => r.sectionIndex === 0)).toBe(true);
  });
});

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
    expect(sections[0].ref).toBeNull();
    // A section without a heading chunk anchors its path's ref (#122).
    expect(sections.map((s) => s.anchor)).toEqual(["Gen.1", "Gen.2"]);
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
    // The heading chunk's ref stays an anchor, so a search result on it resolves.
    expect(sections.map((s) => s.ref)).toEqual(["Ancyra.Canon.1", "Ancyra.Canon.2"]);
    expect(sections.map((s) => s.anchor)).toEqual([null, null]);
  });

  it("joins derived verses back into their source paragraph", () => {
    const sections = parseWork(
      work("Aug.Ep", [
        ["1.1", "Short paragraph."],
        ["1.2.s1", "First sentence."],
        ["1.2.s2", "Second sentence."],
        ["1.3.s1", "Another."],
        ["1.3.s2", "Paragraph.", 1],
        ["2.1", "Next chapter."],
      ]),
      "patristic",
    );
    expect(sections.map((s) => s.units.map((u) => u.n))).toEqual([["1", "2", "3"], ["1"]]);
    const [plain, split, late] = sections[0].units;
    expect(plain.parts).toBeUndefined();
    expect(split.ref).toBe("Aug.Ep.1.2");
    expect(split.text).toBe("First sentence. Second sentence.");
    expect(split.parts).toEqual([
      { n: "1", ref: "Aug.Ep.1.2.s1", text: "First sentence." },
      { n: "2", ref: "Aug.Ep.1.2.s2", text: "Second sentence." },
    ]);
    expect(late.parts?.map((p) => p.ref)).toEqual(["Aug.Ep.1.3.s1", "Aug.Ep.1.3.s2"]);
    expect(late.outOfPeriod).toBe(true);
  });

  it("numbers a whole-work paragraph from the ref prefix", () => {
    const sections = parseWork(
      work("stoa0058.stoa006.1", [
        ["s1", "Christianam fidem."],
        ["s2", "Haec autem."],
      ]),
      "patristic",
    );
    expect(sections).toHaveLength(1);
    expect(sections[0].label).toBeNull();
    const [unit] = sections[0].units;
    expect(unit.n).toBe("1");
    expect(unit.ref).toBe("stoa0058.stoa006.1");
    expect(unit.parts?.map((p) => p.ref)).toEqual(["stoa0058.stoa006.1.s1", "stoa0058.stoa006.1.s2"]);
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
    expect(sections.map((s) => s.ref)).toEqual(["ByzLit.Chrysostom.0001.0000", "ByzLit.Chrysostom.0002.0000"]);
  });

  it("keeps zero-numbered units in prose", () => {
    const [section] = parseWork(work("CopScr.abraham", [["000.0000", "ϭⲟⲗ"], ["000.0001", "ⲛⲉⲛⲧ"]]), "patristic");
    expect(section.title).toBeNull();
    expect(section.units.map((u) => u.n)).toEqual(["0", "1"]);
  });

  it("keeps zero-numbered units in a zero-based source's liturgical work", () => {
    const lament = work("CopScr.lament-mary", [["000.0000", "ⲁⲥⲣⲓⲙⲉ"], ["000.0001", "ⲛⲉⲛⲧ"]]);
    const [section] = parseWork(lament, "liturgical", "coptic-scriptorium");
    expect(section.title).toBeNull();
    expect(section.units.map((u) => u.n)).toEqual(["0", "1"]);
  });

  it("renders apocrypha like prose", () => {
    const [section] = parseWork(work("X", [["0", "TITLE"], ["1", "AMEN"]]), "apocrypha");
    expect(section.title).toBeNull();
    expect(section.units.map((u) => [u.n, u.rubric])).toEqual([
      ["0", false],
      ["1", false],
    ]);
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
    expect(sections.map((s) => s.anchor)).toEqual(["X.1", "X.2", null]);
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

describe("isDerivedRef", () => {
  it("recognises sN as the last segment only", () => {
    expect(isDerivedRef("Aug.Conf.1.1.s3")).toBe(true);
    expect(isDerivedRef("s1")).toBe(true);
    expect(isDerivedRef("Aug.Conf.1.1.3")).toBe(false);
    expect(isDerivedRef("c12.p4")).toBe(false);
    expect(isDerivedRef("Aug.s1.2")).toBe(false);
  });
});

describe("editorial material", () => {
  it("attaches each chunk's editorial spans to its unit or derived verse", () => {
    const sections = parseWork(
      {
        work_id: "w",
        ref_prefix: "CopScr",
        editorial: { "1.1": [[4, 7, "lacuna"]], "1.2.s2": [[0, 3, "lacuna"]] },
        chunks: [
          ["1.1", "ⲁⲩⲱ […] ⲁϥ"],
          ["1.2.s1", "ⲁϥⲥⲱⲧⲙ."],
          ["1.2.s2", "[…] ⲁϥⲉⲓ."],
          ["1.3", "ⲁⲩⲱ ⲁϥ"],
        ],
      },
      "patristic",
    );
    const [plain, split, last] = sections[0].units;
    expect(plain.editorial).toEqual([[4, 7, "lacuna"]]);
    expect(split.editorial).toBeUndefined();
    expect(split.parts?.map((p) => p.editorial)).toEqual([undefined, [[0, 3, "lacuna"]]]);
    expect(split.text).toBe("ⲁϥⲥⲱⲧⲙ. […] ⲁϥⲉⲓ.");
    expect(last.editorial).toBeUndefined();
  });
});
