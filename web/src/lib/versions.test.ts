import { afterEach, describe, expect, it, vi } from "vitest";

import type { AlignmentFile, LibraryIndex, WorkFile, WorkRow } from "./library";
import { workRow } from "./testFixtures";
import { TARGET_ATTRIBUTE } from "./useHashTarget";
import {
  alignmentPosition,
  currentPosition,
  distinguishVersions,
  groupByLanguage,
  mapPosition,
  nativeRef,
  orgRef,
  originalIds,
  positionSuffix,
  scripturePosition,
  versionCounts,
  versionMembers,
  type PositionMapper,
  type PositionRequest,
} from "./versions";

const book = (source: string, language: string, overrides: Partial<WorkRow> = {}) =>
  workRow({
    id: `${source}/ps`,
    source_id: source,
    language,
    title: "Psalms",
    genre: "scripture",
    version_group: "book:ps",
    file: `works/${source}/Ps.json`,
    ...overrides,
  });

const oshb = book("oshb", "hbo");
const lxx = book("lxx-rahlfs", "grc");
const vul = book("clementine", "lat");
const kjv = book("kjv", "eng");
const web = book("web", "eng");

const sources = {
  oshb: "Open Scriptures Hebrew Bible",
  "lxx-rahlfs": "Septuagint (Rahlfs)",
  clementine: "Clementine Vulgate",
  kjv: "King James Version",
  web: "World English Bible",
};

describe("versionMembers", () => {
  const lone = workRow({ id: "pl/lone" });
  const index: LibraryIndex = { version: "v", sources, works: [oshb, lone, kjv, vul] };

  it("returns every work sharing the group, the work itself included", () => {
    expect(versionMembers(index, kjv).map((w) => w.id)).toEqual(["oshb/ps", "kjv/ps", "clementine/ps"]);
  });

  it("returns [] for a work with no other version", () => {
    expect(versionMembers(index, lone)).toEqual([]);
  });

  it("counts the members of each group", () => {
    expect(versionCounts(index.works)).toEqual(new Map([["book:ps", 3]]));
  });
});

describe("originalIds", () => {
  it("follows translation_of to the end of the chain", () => {
    const grc = workRow({ id: "grc", language: "grc" });
    const lat = workRow({ id: "lat", language: "lat", translation_of: "grc" });
    const eng = workRow({ id: "eng", language: "eng", translation_of: "lat" });
    expect(originalIds([eng, lat, grc])).toEqual(new Set(["grc"]));
  });

  it("follows Scripture chains to the Hebrew (#153)", () => {
    // Coptic → LXX → Hebrew; the Vulgate Psalter from the Greek; both Greek
    // editions translate the Hebrew; an unlinked version (source not in the
    // corpus) is not an original either.
    const heb = book("oshb", "hbo", { id: "oshb/ps" });
    const pta = book("pta-lxx", "grc", { id: "pta-lxx/ps", translation_of: "oshb/ps" });
    const rahlfs = book("lxx-rahlfs", "grc", { id: "lxx-rahlfs/ps", translation_of: "oshb/ps" });
    const cop = book("coptic-nt", "cop", { id: "coptic-nt/ps", translation_of: "pta-lxx/ps" });
    const lat = book("clementine", "lat", { id: "clementine/ps", translation_of: "pta-lxx/ps" });
    const gez = book("gez", "gez", { id: "gez/ps" });
    const eng = book("kjv", "eng", { id: "kjv/ps", translation_of: "oshb/ps" });
    expect(originalIds([eng, gez, lat, cop, rahlfs, pta, heb])).toEqual(new Set(["oshb/ps"]));
  });

  it("marks both Greek editions where the Greek is the original (#153)", () => {
    const pta = book("pta-lxx", "grc", { id: "pta-lxx/wis" });
    const rahlfs = book("lxx-rahlfs", "grc", { id: "lxx-rahlfs/wis" });
    const arm = book("armenian", "hye", { id: "armenian/wis", translation_of: "pta-lxx/wis" });
    expect(originalIds([arm, rahlfs, pta])).toEqual(new Set(["pta-lxx/wis", "lxx-rahlfs/wis"]));
  });

  it("ranks Old Georgian after Greek, Syriac and Armenian (#512)", () => {
    const oge = workRow({ id: "oge", language: "oge" });
    const hye = workRow({ id: "hye", language: "hye" });
    const syc = workRow({ id: "syc", language: "syc" });
    const grc = workRow({ id: "grc", language: "grc" });
    expect(originalIds([oge, hye])).toEqual(new Set(["hye"]));
    expect(originalIds([oge, syc])).toEqual(new Set(["syc"]));
    expect(originalIds([oge, grc])).toEqual(new Set(["grc"]));
    const eng = workRow({ id: "eng", language: "eng" });
    expect(originalIds([eng, oge])).toEqual(new Set(["oge"]));
  });

  it("ranks Old Irish after Latin, before the other vernaculars (#544)", () => {
    const sga = workRow({ id: "sga", language: "sga" });
    const lat = workRow({ id: "lat", language: "lat" });
    const grc = workRow({ id: "grc", language: "grc" });
    const chu = workRow({ id: "chu", language: "chu" });
    const eng = workRow({ id: "eng", language: "eng" });
    expect(originalIds([sga, lat])).toEqual(new Set(["lat"]));
    expect(originalIds([sga, grc])).toEqual(new Set(["grc"]));
    expect(originalIds([chu, sga])).toEqual(new Set(["sga"]));
    expect(originalIds([eng, sga])).toEqual(new Set(["sga"]));
  });

  it("marks every edition of the original, but not its translations", () => {
    const first1k = workRow({ id: "first1k", language: "grc" });
    const migne = workRow({ id: "pg", language: "grc" });
    const anf = workRow({ id: "anf", language: "eng", translation_of: "first1k" });
    const anf9 = workRow({ id: "anf9", language: "eng", translation_of: "first1k" });
    expect(originalIds([anf, anf9, first1k, migne])).toEqual(new Set(["first1k", "pg"]));
  });

  it("a translation_of link outranks the language order", () => {
    // A Greek translation of a Latin work (Perpetua's Passion, say).
    const lat = workRow({ id: "lat", language: "lat" });
    const grc = workRow({ id: "grc", language: "grc", translation_of: "lat" });
    expect(originalIds([grc, lat])).toEqual(new Set(["lat"]));
  });

  it("takes Hebrew for the Old Testament when no link says", () => {
    expect(originalIds([kjv, vul, lxx, oshb, web])).toEqual(new Set(["oshb/ps"]));
  });

  it("takes Greek when there is no Hebrew (New Testament)", () => {
    const sbl = book("sblgnt", "grc", { id: "sblgnt/matt" });
    const got = book("wulfila", "got", { id: "wulfila/matt" });
    expect(originalIds([kjv, sbl, got])).toEqual(new Set(["sblgnt/matt"]));
  });

  it("marks nothing in a group of one language or of English only", () => {
    const a = workRow({ id: "a", language: "grc" });
    const b = workRow({ id: "b", language: "grc" });
    expect(originalIds([a, b])).toEqual(new Set());
    expect(originalIds([kjv, web])).toEqual(new Set());
  });

  it("survives a translation_of cycle", () => {
    const a = workRow({ id: "a", language: "grc", translation_of: "b" });
    const b = workRow({ id: "b", language: "lat", translation_of: "a" });
    expect(originalIds([a, b])).toEqual(new Set());
  });
});

describe("groupByLanguage", () => {
  it("puts the original's language first, then languages by name", () => {
    const groups = groupByLanguage([web, vul, kjv, oshb, lxx], new Set(["oshb/ps"]), sources);
    expect(groups.map((g) => g.name)).toEqual(["Hebrew", "English", "Greek", "Latin"]);
    expect(groups[1].works.map((w) => w.id)).toEqual(["kjv/ps", "web/ps"]);
  });

  it("puts originals first within a language", () => {
    const a = workRow({ id: "a", language: "grc", source_id: "ogpg" });
    const b = workRow({ id: "b", language: "grc", source_id: "first1k" });
    const [grc] = groupByLanguage([b, a], new Set(["a"]), { ogpg: "Patrologia Graeca", first1k: "First1K" });
    expect(grc.works.map((w) => w.id)).toEqual(["a", "b"]);
  });
});

// Psalm 22/23 and the Vulgate's Psalm 9/10 split, as exported: KJV and the
// Vulgate number differently from the Hebrew (org) the export maps onto.
const kjvFile: WorkFile = {
  work_id: "kjv/ps",
  ref_prefix: "Ps",
  org_refs: { "3.1": "Ps.3.2", "3.2": "Ps.3.3" },
  chunks: [
    ["3.1", "LORD, how are they increased"],
    ["3.2", "Many there be"],
    ["10.1", "Why standest thou afar off"],
    ["23.1", "The LORD is my shepherd"],
    ["23.2", "He maketh me to lie down"],
  ],
};
const vulFile: WorkFile = {
  work_id: "clementine/ps",
  ref_prefix: "Ps",
  org_refs: { "9.22": "Ps.10.1", "22.1": "Ps.23.1", "22.2": "Ps.23.2" },
  chunks: [
    ["3.1", "Psalmus David"],
    ["3.2", "Domine, quid multiplicati sunt"],
    ["9.22", "Ut quid Domine recessisti longe"],
    ["22.1", "Dominus regit me"],
    ["22.2", "in loco pascuae"],
  ],
};
const oshbFile: WorkFile = {
  work_id: "oshb/ps",
  ref_prefix: "Ps",
  org_refs: {},
  chunks: [
    ["3.1", "מִזְמ֥וֹר לְדָוִ֑ד"],
    ["3.2", "יְ֭הוָה מָה־רַבּ֣וּ צָרָ֑י"],
    ["23.1", "מִזְמ֥וֹר לְדָוִ֑ד יְהֹוָ֥ה רֹ֝עִ֗י"],
  ],
};
const patristic: WorkFile = { work_id: "pl/x", ref_prefix: "", chunks: [["1.1", "Lorem"]] };

describe("orgRef and nativeRef", () => {
  it("maps a native ref to org numbering", () => {
    expect(orgRef(vulFile, "Ps.22.1")).toBe("Ps.23.1");
    expect(orgRef(kjvFile, "Ps.23.1")).toBe("Ps.23.1");
    expect(orgRef(kjvFile, "Ps.3.1")).toBe("Ps.3.2");
  });

  it("maps an org ref to the work's own numbering", () => {
    expect(nativeRef(vulFile, "Ps.23.1")).toBe("Ps.22.1");
    expect(nativeRef(vulFile, "Ps.10.1")).toBe("Ps.9.22");
    expect(nativeRef(kjvFile, "Ps.3.2")).toBe("Ps.3.1");
    expect(nativeRef(oshbFile, "Ps.3.2")).toBe("Ps.3.2");
  });

  it("falls back to the chapter, then to nothing", () => {
    expect(nativeRef(vulFile, "Ps.23.6")).toBe("Ps.22.1");
    expect(nativeRef(vulFile, "Ps.150.1")).toBeNull();
  });

  it("does not apply to works that are not Scripture books", () => {
    expect(orgRef(patristic, "1.1")).toBeNull();
    expect(nativeRef(patristic, "1.1")).toBeNull();
  });
});

const plRow = workRow({ id: "pl/x", version_group: "pl/x" });

/** A work file as published before org_refs existed (#144). */
function withoutOrgRefs(file: WorkFile): WorkFile {
  const copy = { ...file };
  delete copy.org_refs;
  return copy;
}

function request(fromWork: WorkFile, ref: string, toWork: WorkFile, from = kjv, to = vul): PositionRequest {
  return { from, fromWork, ref, to, loadTarget: async () => toWork };
}

/** The mapped ref alone. */
async function mappedRef(req: PositionRequest, mappers?: readonly PositionMapper[]): Promise<string | null> {
  return (await mapPosition(req, mappers))?.ref ?? null;
}

describe("mapPosition", () => {
  it("keeps the verse across numberings (KJV ↔ Vulgate ↔ Hebrew)", async () => {
    expect(await mappedRef(request(kjvFile, "Ps.23.1", vulFile))).toBe("Ps.22.1");
    expect(await mappedRef(request(vulFile, "Ps.22.2", kjvFile))).toBe("Ps.23.2");
    expect(await mappedRef(request(kjvFile, "Ps.10.1", vulFile))).toBe("Ps.9.22");
    // The KJV's first verse of Psalm 3 is the Hebrew's second (its title is verse 1).
    expect(await mappedRef(request(kjvFile, "Ps.3.1", oshbFile))).toBe("Ps.3.2");
    expect(await mappedRef(request(oshbFile, "Ps.3.2", kjvFile))).toBe("Ps.3.1");
  });

  it("opens other works at the top", async () => {
    expect(await mappedRef(request(patristic, "1.1", patristic, plRow, plRow))).toBeNull();
    expect(await mappedRef(request(kjvFile, "Ps.23.1", patristic, kjv, plRow))).toBeNull();
  });

  it("does not load the target unless the current work is Scripture", async () => {
    const loadTarget = vi.fn(async () => vulFile);
    expect(await scripturePosition({ ...request(patristic, "1.1", vulFile, plRow, vul), loadTarget })).toBeUndefined();
    expect(loadTarget).not.toHaveBeenCalled();
  });

  it("reads a Scripture book without org_refs (an older library) as org numbering", async () => {
    const oldKjv = withoutOrgRefs(kjvFile);
    const oldVul = withoutOrgRefs(vulFile);
    // Neither side mapped: the same ref, else the same chapter.
    expect(await mappedRef(request(oldKjv, "Ps.3.2", oldVul))).toBe("Ps.3.2");
    expect(await mappedRef(request(oldKjv, "Ps.3.9", oldVul))).toBe("Ps.3.1");
    expect(await mappedRef(request(oldKjv, "Ps.23.1", oldVul))).toBeNull();
    // Only the target unmapped: org ref read as the target's own.
    expect(await mappedRef(request(kjvFile, "Ps.3.1", oldVul))).toBe("Ps.3.2");
    // Only the source unmapped: its ref read as org.
    expect(await mappedRef(request(oldKjv, "Ps.23.1", vulFile))).toBe("Ps.22.1");
  });

  it("does not guess across works outside a Scripture book group", async () => {
    const bookless = workRow({ id: "x/ps", version_group: "x/ps" });
    const req = request(withoutOrgRefs(kjvFile), "Ps.23.1", withoutOrgRefs(vulFile), bookless, bookless);
    expect(await scripturePosition(req)).toBeUndefined();
  });

  it("tries further mappers in order (passage alignment, #179)", async () => {
    const aligned: PositionMapper = async ({ ref }) => `aligned:${ref}`;
    expect(await mappedRef(request(patristic, "1.1", patristic, plRow, plRow), [scripturePosition, aligned])).toBe(
      "aligned:1.1",
    );
    expect(await mappedRef(request(kjvFile, "Ps.23.1", vulFile), [scripturePosition, aligned])).toBe(
      "Ps.22.1",
    );
  });
});

// A letter in three versions (#179): the English (pivot) splits paragraph 2
// into derived verses, the Greek joins what the English has as one paragraph
// into two (n:m), and the Latin has a preface nothing else has.
const letter = (id: string, language: string) =>
  workRow({ id, language, version_group: "grc/ep", file: `works/${id}.json` });
const engRow = letter("eng/ep", "eng");
const grcRow = letter("grc/ep", "grc");
const latRow = letter("lat/ep", "lat");
const engEp: WorkFile = {
  work_id: "eng/ep",
  ref_prefix: "",
  chunks: [
    ["1", "Paul to the Church"], // group 0
    ["2.s1", "Grace to you."], // group 1
    ["2.s2", "And peace."], // group 1
    ["3", "I give thanks"], // group 2: flagged in the Greek
    ["4", "A gloss"], // no group
    ["5", "Farewell"], // group 3: not in the Greek
  ],
};
const grcEp: WorkFile = {
  work_id: "grc/ep",
  ref_prefix: "Ep",
  chunks: [
    ["1.1", "Παῦλος"],
    ["1.2", "τῇ ἐκκλησίᾳ"], // group 0, with 1.1
    ["2", "χάρις ὑμῖν καὶ εἰρήνη"], // group 1
    ["3", "εὐχαριστῶ"], // group 2, confidence 3
  ],
};
const latEp: WorkFile = {
  work_id: "lat/ep",
  ref_prefix: "",
  chunks: [
    ["praef", "Praefatio"], // no group
    ["1", "Paulus ecclesiae"],
    ["2", "Gratia vobis et pax"],
    ["3", "Gratias ago"],
    ["4", "Valete"],
  ],
};
const epAlignment: AlignmentFile = {
  group: "grc/ep",
  pivot: "eng/ep",
  groups: 4,
  members: {
    "eng/ep": { units: 6, spans: "++=+.+", conf: "9999" },
    "grc/ep": { units: 4, spans: "+=++", conf: "993" },
    "lat/ep": { units: 5, spans: ".++++", conf: "9999" },
  },
};
const epFiles = new Map([
  [engRow.id, engEp],
  [grcRow.id, grcEp],
  [latRow.id, latEp],
]);

function aligned(from: WorkRow, ref: string, to: WorkRow, file: AlignmentFile | null = epAlignment): PositionRequest {
  return {
    from,
    fromWork: epFiles.get(from.id)!,
    ref,
    to,
    loadTarget: async () => epFiles.get(to.id)!,
    loadAlignment: file ? async () => file : undefined,
  };
}

describe("alignmentPosition", () => {
  it("opens the first unit of the same passage, across n:m spans and derived verses", async () => {
    expect(await mapPosition(aligned(engRow, "1", grcRow))).toEqual({ ref: "Ep.1.1", approximate: false });
    expect(await mappedRef(aligned(grcRow, "Ep.1.2", engRow))).toBe("1");
    expect(await mappedRef(aligned(engRow, "2.s2", grcRow))).toBe("Ep.2");
    // A split paragraph's element carries the source unit's ref.
    expect(await mappedRef(aligned(engRow, "2", grcRow))).toBe("Ep.2");
    expect(await mappedRef(aligned(grcRow, "Ep.2", engRow))).toBe("2.s1");
  });

  it("maps a work that is one split paragraph from its paragraph ref (the ref prefix)", async () => {
    const whole: WorkFile = { work_id: "eng/ep", ref_prefix: "Ep", chunks: [["s1", "Paul"], ["s2", "Grace"], ["s3", "Thanks"], ["s4", "Gloss"], ["s5", "Farewell"], ["s6", "Amen"]] };
    const req = { ...aligned(engRow, "Ep", grcRow), fromWork: whole };
    expect(await mapPosition(req)).toEqual({ ref: "Ep.1.1", approximate: false });
  });

  it("works between any two members, not only with the pivot", async () => {
    expect(await mappedRef(aligned(latRow, "2", grcRow))).toBe("Ep.2");
    expect(await mappedRef(aligned(grcRow, "Ep.1.1", latRow))).toBe("1");
    expect(await mappedRef(aligned(engRow, "3", latRow))).toBe("3");
    expect(await mappedRef(aligned(engRow, "5", latRow))).toBe("4");
  });

  it("falls back to the nearest preceding aligned unit, as an approximate position", async () => {
    // Group 2 is flagged in the Greek; 4 has no group; group 3 isn't in the Greek.
    for (const ref of ["3", "4", "5"]) {
      expect(await mapPosition(aligned(engRow, ref, grcRow))).toEqual({ ref: "Ep.2", approximate: true });
    }
    expect(await mapPosition(aligned(engRow, "4", latRow))).toEqual({ ref: "3", approximate: true });
    expect(await mapPosition(aligned(grcRow, "Ep.3", latRow))).toEqual({ ref: "2", approximate: true });
  });

  it("opens at the top when nothing before the passage is aligned, or the ref is unknown", async () => {
    expect(await mapPosition(aligned(latRow, "praef", engRow))).toBeNull();
    expect(await mapPosition(aligned(engRow, "s-text", latRow))).toBeNull();
  });

  it("doesn't apply without an alignment, or to a member the file leaves out", async () => {
    expect(await alignmentPosition(aligned(engRow, "1", grcRow, null))).toBeUndefined();
    const withoutGrc = { ...epAlignment, members: { "eng/ep": epAlignment.members["eng/ep"] } };
    expect(await alignmentPosition(aligned(engRow, "1", grcRow, withoutGrc))).toBeUndefined();
    const failing = { ...aligned(engRow, "1", grcRow), loadAlignment: () => Promise.reject(new Error("404")) };
    expect(await alignmentPosition(failing)).toBeUndefined();
    const elsewhere = { ...grcRow, version_group: "other" };
    expect(await alignmentPosition(aligned(engRow, "1", elsewhere))).toBeUndefined();
  });

  it("opens at the top when a work file doesn't have the units the alignment counts", async () => {
    const staleTarget = { ...aligned(engRow, "1", grcRow), loadTarget: async () => latEp };
    expect(await mapPosition(staleTarget)).toBeNull();
    const staleSource = { ...aligned(engRow, "1", grcRow), fromWork: latEp };
    expect(await mapPosition(staleSource)).toBeNull();
  });

  it("leaves Scripture to the versification mapper", async () => {
    const loadAlignment = vi.fn(async () => epAlignment);
    expect(await mappedRef({ ...request(kjvFile, "Ps.23.1", vulFile), loadAlignment })).toBe("Ps.22.1");
    expect(loadAlignment).not.toHaveBeenCalled();
  });

  it("finds its way in a group with many members", async () => {
    // Twelve editions, each with one more unaligned preface unit than the last.
    const rows = Array.from({ length: 12 }, (_, i) => letter(`ed${i}/ep`, "lat"));
    const files = new Map<string, WorkFile>();
    const members: AlignmentFile["members"] = {};
    rows.forEach((row, i) => {
      const chunks: WorkFile["chunks"] = [];
      for (let p = 0; p < i; p++) chunks.push([`p${p}`, "praefatio"]);
      for (let u = 1; u <= 50; u++) chunks.push([String(u), `unit ${u}`]);
      files.set(row.id, { work_id: row.id, ref_prefix: "", chunks });
      members[row.id] = { units: chunks.length, spans: ".".repeat(i) + "+".repeat(50), conf: "9".repeat(50) };
    });
    const file: AlignmentFile = { group: "grc/ep", pivot: rows[0].id, groups: 50, members };
    for (const [a, b] of [
      [0, 11],
      [11, 0],
      [5, 7],
    ]) {
      const req: PositionRequest = {
        from: rows[a],
        fromWork: files.get(rows[a].id)!,
        ref: "37",
        to: rows[b],
        loadTarget: async () => files.get(rows[b].id)!,
        loadAlignment: async () => file,
      };
      expect(await mapPosition(req)).toEqual({ ref: "37", approximate: false });
    }
  });
});

describe("currentPosition", () => {
  // jsdom has no layout: give each element a box (top, bottom) by id.
  function layout(boxes: Record<string, [number, number]>) {
    vi.spyOn(Element.prototype, "getBoundingClientRect").mockImplementation(function (this: Element) {
      const [top, bottom] = boxes[this.id] ?? [0, 0];
      return { top, bottom } as DOMRect;
    });
  }

  function text(): HTMLElement {
    const div = document.createElement("div");
    div.id = "text";
    div.innerHTML = `
      <section id="s-1"><h2>Chapter 1</h2><p><span id="Ps.1.1">a</span><span id="Ps.1.2">b</span></p></section>
      <section id="s-2"><p><span id="Ps.2.1">c</span><span id="Ps.2.2">d</span></p></section>`;
    document.body.append(div);
    return div;
  }

  afterEach(() => {
    vi.restoreAllMocks();
    document.body.innerHTML = "";
    window.location.hash = "";
  });

  it("is the first passage at the top of the viewport, not highlighted", () => {
    const div = text();
    layout({ text: [-900, 1000], "s-1": [-900, -10], "s-2": [-10, 600], "Ps.2.1": [-10, -2], "Ps.2.2": [-2, 40] });
    expect(currentPosition(div, "")).toEqual({ ref: "Ps.2.2", highlight: false });
  });

  it("is the fragment's passage while it is on screen, highlighted if it is marked", () => {
    const div = text();
    layout({ text: [-900, 1000], "s-1": [-900, -10], "s-2": [-10, 600], "Ps.1.2": [-400, -380], "Ps.2.2": [200, 230] });
    // Opened with ?nohl: on screen but not marked.
    expect(currentPosition(div, "#Ps.2.2")).toEqual({ ref: "Ps.2.2", highlight: false });
    document.getElementById("Ps.2.2")!.setAttribute(TARGET_ATTRIBUTE, "");
    expect(currentPosition(div, "#Ps.2.2")).toEqual({ ref: "Ps.2.2", highlight: true });
    // Scrolled away from it: the top of the viewport wins.
    document.getElementById("Ps.1.2")!.setAttribute(TARGET_ATTRIBUTE, "");
    expect(currentPosition(div, "#Ps.1.2")).toEqual({ ref: "Ps.2.2", highlight: false });
  });

  it("is null before the reader has scrolled into the text", () => {
    const div = text();
    layout({ text: [300, 2000], "s-1": [300, 900], "Ps.1.1": [300, 330] });
    expect(currentPosition(div, "")).toBeNull();
    expect(currentPosition(null, "")).toBeNull();
  });
});

describe("distinguishVersions", () => {
  it("adds the title where it differs and the edition only where entries tie", () => {
    const current = workRow({ id: "grc", language: "grc", title: "Epistula" });
    const anf1 = workRow({ id: "anf1", language: "eng", source_id: "anf-works", title: "Epistle", edition: "ANF Vol. 1" });
    const anf9 = workRow({ id: "anf9", language: "eng", source_id: "anf-works", title: "Epistle", edition: "ANF Vol. 9" });
    const npnf = workRow({ id: "npnf", language: "eng", source_id: "npnf-works", title: "Epistle", edition: "NPNF" });
    const pg = workRow({ id: "pg", language: "grc", source_id: "ogpg", title: "Epistula", edition: "PG 1" });
    const details = distinguishVersions([anf1, anf9, npnf, pg], current, { "anf-works": "ANF", "npnf-works": "NPNF" });
    expect(details.get("anf1")).toEqual({ title: "Epistle", edition: "ANF Vol. 1" });
    expect(details.get("anf9")).toEqual({ title: "Epistle", edition: "ANF Vol. 9" });
    expect(details.get("npnf")).toEqual({ title: "Epistle", edition: null });
    expect(details.get("pg")).toEqual({ title: null, edition: null });
  });
});

describe("positionSuffix", () => {
  it("keeps a highlighted passage highlighted, and only scrolls to a scroll position", () => {
    expect(positionSuffix({ ref: "Ps.22.1", highlight: true })).toBe("#Ps.22.1");
    expect(positionSuffix({ ref: "Ps.22.1", highlight: false })).toBe("?nohl#Ps.22.1");
    expect(positionSuffix(null)).toBe("");
  });
});
