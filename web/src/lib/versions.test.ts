import { afterEach, describe, expect, it, vi } from "vitest";

import type { LibraryIndex, WorkFile, WorkRow } from "./library";
import { workRow } from "./testFixtures";
import {
  currentRef,
  groupByLanguage,
  mapPosition,
  nativeRef,
  orgRef,
  originalIds,
  refHash,
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

function request(fromWork: WorkFile, ref: string, toWork: WorkFile): PositionRequest {
  return { from: kjv, fromWork, ref, to: vul, loadTarget: async () => toWork };
}

describe("mapPosition", () => {
  it("keeps the verse across numberings (KJV ↔ Vulgate ↔ Hebrew)", async () => {
    expect(await mapPosition(request(kjvFile, "Ps.23.1", vulFile))).toBe("Ps.22.1");
    expect(await mapPosition(request(vulFile, "Ps.22.2", kjvFile))).toBe("Ps.23.2");
    expect(await mapPosition(request(kjvFile, "Ps.10.1", vulFile))).toBe("Ps.9.22");
    // The KJV's first verse of Psalm 3 is the Hebrew's second (its title is verse 1).
    expect(await mapPosition(request(kjvFile, "Ps.3.1", oshbFile))).toBe("Ps.3.2");
    expect(await mapPosition(request(oshbFile, "Ps.3.2", kjvFile))).toBe("Ps.3.1");
  });

  it("opens other works at the top", async () => {
    expect(await mapPosition(request(patristic, "1.1", patristic))).toBeNull();
    expect(await mapPosition(request(kjvFile, "Ps.23.1", patristic))).toBeNull();
  });

  it("does not load the target unless the current work is Scripture", async () => {
    const loadTarget = vi.fn(async () => vulFile);
    expect(await scripturePosition({ ...request(patristic, "1.1", vulFile), loadTarget })).toBeUndefined();
    expect(loadTarget).not.toHaveBeenCalled();
  });

  it("tries further mappers in order (passage alignment, #179)", async () => {
    const aligned: PositionMapper = async ({ ref }) => `aligned:${ref}`;
    expect(await mapPosition(request(patristic, "1.1", patristic), [scripturePosition, aligned])).toBe(
      "aligned:1.1",
    );
    expect(await mapPosition(request(kjvFile, "Ps.23.1", vulFile), [scripturePosition, aligned])).toBe(
      "Ps.22.1",
    );
  });
});

describe("currentRef", () => {
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

  it("is the first passage at the top of the viewport", () => {
    const div = text();
    layout({ text: [-900, 1000], "s-1": [-900, -10], "s-2": [-10, 600], "Ps.2.1": [-10, -2], "Ps.2.2": [-2, 40] });
    expect(currentRef(div, "")).toBe("Ps.2.2");
  });

  it("is the fragment's passage while it is on screen", () => {
    const div = text();
    layout({ text: [-900, 1000], "s-1": [-900, -10], "s-2": [-10, 600], "Ps.1.2": [-400, -380], "Ps.2.2": [200, 230] });
    expect(currentRef(div, "#Ps.2.2")).toBe("Ps.2.2");
    // Scrolled away from it: the top of the viewport wins.
    expect(currentRef(div, "#Ps.1.2")).toBe("Ps.2.2");
  });

  it("is null before the reader has scrolled into the text", () => {
    const div = text();
    layout({ text: [300, 2000], "s-1": [300, 900], "Ps.1.1": [300, 330] });
    expect(currentRef(div, "")).toBeNull();
    expect(currentRef(null, "")).toBeNull();
  });
});

describe("refHash", () => {
  it("builds a fragment", () => {
    expect(refHash("Ps.22.1")).toBe("#Ps.22.1");
    expect(refHash(null)).toBe("");
  });
});
