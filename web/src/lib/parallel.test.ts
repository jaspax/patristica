import { describe, expect, it } from "vitest";

import { decodeMember, type AlignedMember } from "./alignment";
import type { LibraryIndex, WorkFile } from "./library";
import {
  buildRows,
  canReadInParallel,
  columnRef,
  keepPosition,
  longestIncreasing,
  MAX_VERSIONS,
  parallelHref,
  parallelIds,
  parallelVersions,
  sectionBlocks,
  splitColumnRef,
  versificationMembers,
  withPosition,
  type Row,
} from "./parallel";
import { chunkRoles, parseWork } from "./render";
import { workRow } from "./testFixtures";

const member = (spans: string, conf?: string): AlignedMember => {
  const units = spans.match(/\.|=|[+-]\d*/g)!.length;
  const m = decodeMember({ units, spans, conf: conf ?? "9".repeat(countGroups(spans)) });
  if (!m) throw new Error(`bad fixture ${spans}`);
  return m;
};

function countGroups(spans: string): number {
  return (spans.match(/[+-]\d*/g) ?? []).length;
}

/** Rows as [column cells] with "a-b" spans, "" for an empty cell. */
const show = (rows: Row[]) => rows.map((r) => r.cells.map((c) => (c ? `${c[0]}-${c[1]}` : "")).join("|"));

describe("URL state", () => {
  it("reads the other versions in order, once each, without the work itself", () => {
    const params = new URLSearchParams("with=b&with=a&with=b&with=lead&with=");
    expect(parallelIds(params, "lead")).toEqual(["b", "a"]);
    expect(parallelIds(new URLSearchParams(""), "lead")).toEqual([]);
  });

  it("builds shareable URLs and keeps the position", () => {
    expect(parallelHref("kjv/ps", ["oshb/ps", "clementine/ps"])).toBe("/works/kjv/ps?with=oshb%2Fps&with=clementine%2Fps");
    expect(parallelHref("kjv/ps", [])).toBe("/works/kjv/ps");
    expect(withPosition("/works/kjv/ps?with=oshb%2Fps", { ref: "Ps.23.1", highlight: true })).toBe(
      "/works/kjv/ps?with=oshb%2Fps#Ps.23.1",
    );
    expect(withPosition("/works/kjv/ps?with=oshb%2Fps", { ref: "Ps.23.1", highlight: false })).toBe(
      "/works/kjv/ps?with=oshb%2Fps&nohl#Ps.23.1",
    );
    expect(withPosition("/works/kjv/ps", { ref: "Ps.23.1", highlight: false })).toBe("/works/kjv/ps?nohl#Ps.23.1");
    expect(withPosition("/works/kjv/ps", null)).toBe("/works/kjv/ps");
  });

  it("gives a passage in another version's column a fragment of its own, and keeps it while that version is shown", () => {
    const works = ["kjv/ps", "clementine/ps"];
    expect(columnRef("Ps.22.1", "clementine/ps")).toBe("Ps.22.1@clementine/ps");
    expect(splitColumnRef("Ps.22.1@clementine/ps", works)).toEqual({ ref: "Ps.22.1", work: "clementine/ps" });
    expect(splitColumnRef("Ps.22.1", works)).toEqual({ ref: "Ps.22.1", work: "kjv/ps" });
    // A version not in the view: read as the leading version's id.
    expect(splitColumnRef("Ps.22.1@oshb/ps", works)).toEqual({ ref: "Ps.22.1@oshb/ps", work: "kjv/ps" });
    const at = { ref: "Ps.22.1", work: "clementine/ps", highlight: true };
    expect(keepPosition(at, "kjv/ps", ["clementine/ps"])).toEqual({ ref: "Ps.22.1@clementine/ps", highlight: true });
    expect(keepPosition(at, "clementine/ps", ["kjv/ps"])).toEqual({ ref: "Ps.22.1", highlight: true });
    expect(keepPosition(at, "kjv/ps", [])).toBeNull();
  });

  it("shows the group's members only, at most MAX_VERSIONS", () => {
    const lead = workRow({ id: "a", version_group: "g" });
    const others = ["b", "c", "d", "e"].map((id) => workRow({ id, version_group: "g" }));
    const stranger = workRow({ id: "x", version_group: "other" });
    const index: LibraryIndex = { version: "v", sources: {}, works: [lead, ...others, stranger] };
    const { columns, skipped } = parallelVersions(index, lead, ["x", "b", "nope", "c", "d", "e"]);
    expect(columns.map((w) => w.id)).toEqual(["a", "b", "c", "d"]);
    expect(columns).toHaveLength(MAX_VERSIONS);
    expect(skipped).toEqual([
      { id: "x", reason: "not-a-version" },
      { id: "nope", reason: "unknown" },
      { id: "e", reason: "too-many" },
    ]);
  });

  it("offers parallel reading for Scripture books and aligned groups only", () => {
    const book = workRow({ id: "kjv/ps", version_group: "book:ps" });
    const aligned = workRow({ id: "a", version_group: "a" });
    const index: LibraryIndex = { version: "v", sources: {}, works: [book, aligned], alignments: ["a"] };
    expect(canReadInParallel(index, book)).toBe(true);
    expect(canReadInParallel(index, aligned)).toBe(true);
    expect(canReadInParallel({ ...index, alignments: undefined }, aligned)).toBe(false);
    expect(canReadInParallel(index, workRow({ id: "z", version_group: null }))).toBe(false);
  });
});

describe("longestIncreasing", () => {
  it("finds the indices of a longest strictly increasing run", () => {
    expect([...longestIncreasing([0, 1, 5, 2, 3, 4])].sort()).toEqual([0, 1, 3, 4, 5]);
    expect(longestIncreasing([]).size).toBe(0);
    expect(longestIncreasing([3, 3, 3]).size).toBe(1);
  });
});

describe("buildRows", () => {
  it("puts each alignment group in one row, n:m", () => {
    // Lead: units 0 | 1 2 | 3. Other: units 0 1 | 2 | 3.
    const rows = buildRows([member("++=+"), member("+=++")]);
    expect(show(rows)).toEqual(["0-1|0-2", "1-3|2-3", "3-4|3-4"]);
  });

  it("gives a unit with no counterpart its own row, with an empty cell beside it", () => {
    // Lead unit 1 and the other's unit 0 are in no group.
    const rows = buildRows([member("+.+"), member(".++")]);
    expect(show(rows)).toEqual(["|0-1", "0-1|1-2", "1-2|", "2-3|2-3"]);
  });

  it("keeps a group only one version has as an unpaired row", () => {
    // Groups 0 1 3 in the lead, 0 2 3 in the other: 1 and 2 are each one version's alone.
    const rows = buildRows([member("+++2"), member("++2+")]);
    expect(show(rows)).toEqual(["0-1|0-1", "1-2|", "|1-2", "2-3|2-3"]);
  });

  it("keeps each column in its own order when a version moves a passage", () => {
    // The other version has the lead's group 3 first (a moved block): it can't
    // be beside the lead's group 3 without reordering the column, so it is unpaired.
    const lead = member("++++");
    const moved = member("+4-3++");
    const rows = buildRows([lead, moved]);
    expect(show(rows)).toEqual(["|0-1", "0-1|1-2", "1-2|2-3", "2-3|3-4", "3-4|"]);
  });

  it("marks the versions whose span in a group is below the confidence threshold", () => {
    const rows = buildRows([member("++", "99"), member("++", "39")]);
    expect(rows.map((r) => r.uncertain)).toEqual([
      [false, true],
      [false, false],
    ]);
  });

  it("aligns any number of columns on the lead", () => {
    const rows = buildRows([member("++"), member("+"), member(".+2"), member("+=+")]);
    // The third version's unaligned first unit comes before the first passage they share.
    expect(show(rows)).toEqual(["||0-1|", "0-1|0-1||0-2", "1-2||1-2|2-3"]);
  });

  it("shares a gap row only where it keeps every column in its own order", () => {
    // Groups [0,2], [0,1,2] and [0,-1,1,2]: the third version's unaligned unit
    // comes before its group 1, which the second version's row already holds.
    const unaligned = buildRows([member("++2"), member("+++"), member("+.++")]);
    expect(show(unaligned)).toEqual(["0-1|0-1|0-1", "|1-2|", "||1-2", "||2-3", "1-2|2-3|3-4"]);
    // The same with a group only the third version has ([0,3,1,2]).
    const private_ = buildRows([member("++2"), member("+++"), member("++3-2+")]);
    expect(show(private_)).toEqual(["0-1|0-1|0-1", "|1-2|", "||1-2", "||2-3", "1-2|2-3|3-4"]);
    // Each column's units still come in order.
    for (const rows of [unaligned, private_]) {
      const third = rows.map((r) => r.cells[2]?.[0]).filter((u) => u !== undefined);
      expect(third).toEqual([0, 1, 2, 3]);
    }
  });

  it("marks uncertain spans in a gap row the secondary versions share", () => {
    // Groups [0], [0,1], [0,1]: group 1 pairs the two other versions; the third's span is flagged.
    const rows = buildRows([member("+"), member("++", "99"), member("++", "93")]);
    expect(show(rows)).toEqual(["0-1|0-1|0-1", "|1-2|1-2"]);
    expect(rows[1].uncertain).toEqual([false, false, true]);
  });

  it("is empty without a leading version", () => {
    expect(buildRows([])).toEqual([]);
  });
});

describe("versificationMembers", () => {
  const kjv: WorkFile = {
    work_id: "kjv/ps",
    ref_prefix: "Ps",
    org_refs: { "3.1": "Ps.3.2" },
    chunks: [
      ["3.1", "LORD, how are they increased"],
      ["23.1", "The LORD is my shepherd"],
    ],
  };
  const vul: WorkFile = {
    work_id: "clementine/ps",
    ref_prefix: "Ps",
    org_refs: { "22.1": "Ps.23.1" },
    chunks: [
      ["3.1", "Psalmus David"],
      ["3.2", "Domine, quid multiplicati sunt"],
      ["22.1", "Dominus regit me"],
    ],
  };
  const oshb: WorkFile = {
    work_id: "oshb/ps",
    ref_prefix: "Ps",
    chunks: [
      ["3.1", "מִזְמ֥וֹר לְדָוִ֑ד"],
      ["3.2", "יְ֭הוָה מָה־רַבּ֣וּ צָרָ֑י"],
      ["23.1", "מִזְמ֥וֹר לְדָוִ֑ד יְהֹוָ֥ה רֹ֝עִ֗י"],
    ],
  };

  it("pairs verses by org versification across numberings", () => {
    const rows = buildRows(versificationMembers([kjv, vul, oshb]));
    // The psalm titles (org 3.1) are unpaired in the KJV; KJV 3:1 = Vulgate 3:2 = Hebrew 3:2; KJV 23:1 = Vulgate 22:1.
    expect(show(rows)).toEqual(["|0-1|0-1", "0-1|1-2|1-2", "1-2|2-3|2-3"]);
  });

  it("joins verses that map to the same org verse into one span, and leaves a repeat elsewhere unaligned", () => {
    const merged: WorkFile = {
      work_id: "m",
      ref_prefix: "Ps",
      org_refs: { "3.2": "Ps.3.1", "3.9": "Ps.3.1" },
      chunks: [
        ["3.1", "a"],
        ["3.2", "b"],
        ["23.1", "c"],
        ["3.9", "d"],
      ],
    };
    const [m] = versificationMembers([merged]);
    expect(m.groupOf).toEqual([0, 0, 1, -1]);
  });

  it("pairs the ASV's title unit (Ps.N.0) with the other versions' title verse (#220)", () => {
    const asv: WorkFile = {
      work_id: "asv/ps",
      ref_prefix: "Ps",
      org_refs: { "3.0": "Ps.3.1", "3.1": "Ps.3.2", "23.0": "Ps.23.1" },
      chunks: [
        ["3.0", "A Psalm of David, when he fled from Absalom his son."],
        ["3.1", "Jehovah, how are mine adversaries increased!"],
        ["23.0", "A Psalm of David."],
        ["23.1", "Jehovah is my shepherd"],
      ],
    };
    // Leading: title beside title, verse beside verse; Hebrew 23:1 (title and verse) spans ASV 23:0–1.
    expect(show(buildRows(versificationMembers([asv, kjv, vul, oshb])))).toEqual([
      "0-1||0-1|0-1",
      "1-2|0-1|1-2|1-2",
      "2-4|1-2|2-3|2-3",
    ]);
    // Following the KJV: the shared title row stays before verse 1.
    expect(show(buildRows(versificationMembers([kjv, asv, oshb])))).toEqual(["|0-1|0-1", "0-1|1-2|1-2", "1-2|2-4|2-3"]);
    // The ASV's title is a heading in the reader.
    const [section] = parseWork(asv, "scripture");
    expect(section.title).toBe("A Psalm of David, when he fled from Absalom his son.");
  });
});

describe("sectionBlocks", () => {
  const work: WorkFile = {
    work_id: "w",
    ref_prefix: "",
    chunks: [
      ["1", "Book One"],
      ["1.1", "a"],
      ["1.2", "b"],
      ["2", "Book Two"],
      ["2.1", "c"],
    ],
  };
  const sections = parseWork(work, "patristic");
  const roles = chunkRoles(work, sections);
  const row = (lead: [number, number] | null, other: [number, number] | null = null): Row => ({
    key: `${lead}|${other}`,
    cells: [lead, other],
    uncertain: [false, false],
  });

  it("groups rows by the leading version's sections; rows without a leading unit stay with the row before", () => {
    const rows = [row(null, [0, 1]), row([0, 2], [1, 2]), row(null, [2, 3]), row([2, 3]), row([3, 5], [3, 4])];
    const blocks = sectionBlocks(rows, sections, roles);
    expect(blocks.map((b) => [b.section.id, b.rows.length])).toEqual([
      ["s-1", 4],
      ["s-2", 1],
    ]);
  });

  it("anchors a section that starts inside a row, so the table of contents finds it", () => {
    const blocks = sectionBlocks([row([0, 2]), row([2, 5])], sections, roles);
    expect(blocks.map((b) => b.section.id)).toEqual(["s-1"]);
    expect(blocks[0].starts).toEqual([[], ["s-2"]]);
  });
});
