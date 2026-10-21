import { act, cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { AlignmentFile, Library, LibraryIndex, WorkFile } from "@/lib/library";
import { workRow } from "@/lib/testFixtures";

const push = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push }),
  useParams: () => ({ id: [] }),
  useSearchParams: () => new URLSearchParams(window.location.search),
}));

const book = (id: string, language: string, source: string, license = "public_domain") =>
  workRow({ id, language, source_id: source, title: "Psalms", genre: "scripture", version_group: "book:ps", license, file: `works/${id}.json` });
const kjv = book("kjv/ps", "eng", "kjv");
const oshb = book("oshb/ps", "hbo", "oshb", "cc-by-4.0");
const vul = book("clementine/ps", "lat", "clementine");
const lxx = book("lxx-rahlfs/ps", "grc", "lxx-rahlfs", "cc-by-nc-sa-4.0");
const sinai = book("sinai/ps", "grc", "sinai");

const letter = (id: string, language: string, source: string, title: string) =>
  workRow({ id, language, source_id: source, title, version_group: "grc/ep", file: `works/${id}.json` });
const engEp = letter("eng/ep", "eng", "npnf-works", "Letter");
const grcEp = letter("grc/ep", "grc", "first1k", "Epistula");
const latEp = letter("lat/ep", "lat", "pl", "Epistula");

const index: LibraryIndex = {
  version: "v",
  sources: { kjv: "KJV", oshb: "OSHB", clementine: "Vulgate", "lxx-rahlfs": "Rahlfs", sinai: "Sinai", "npnf-works": "NPNF", first1k: "First1K", pl: "PL" },
  works: [kjv, oshb, vul, lxx, sinai, engEp, grcEp, latEp],
  alignments: ["grc/ep"],
};

const files: Record<string, WorkFile | AlignmentFile> = {
  "/works/kjv/ps.json": {
    work_id: "kjv/ps",
    ref_prefix: "Ps",
    org_refs: { "3.1": "Ps.3.2" },
    chunks: [
      ["3.1", "LORD, how are they increased"],
      ["22.1", "My God, my God"],
      ["23.1", "The LORD is my shepherd"],
    ],
  },
  "/works/oshb/ps.json": {
    work_id: "oshb/ps",
    ref_prefix: "Ps",
    org_refs: {},
    chunks: [
      ["3.1", "מִזְמ֥וֹר לְדָוִ֑ד"],
      ["3.2", "יְ֭הוָה מָה־רַבּ֣וּ צָרָ֑י"],
      ["23.1", "יְהֹוָ֥ה רֹ֝עִ֗י"],
    ],
  },
  "/works/clementine/ps.json": {
    work_id: "clementine/ps",
    ref_prefix: "Ps",
    org_refs: { "21.1": "Ps.22.1", "22.1": "Ps.23.1" },
    chunks: [
      ["3.2", "Domine, quid multiplicati sunt"],
      ["21.1", "Deus, Deus meus"],
      ["22.1", "Dominus regit me"],
    ],
  },
  "/works/eng/ep.json": {
    work_id: "eng/ep",
    ref_prefix: "",
    chunks: [
      ["1", "Paul to the Church"],
      ["2.s1", "Grace to you."],
      ["2.s2", "And peace."],
      ["3", "I give thanks"],
    ],
  },
  "/works/grc/ep.json": {
    work_id: "grc/ep",
    ref_prefix: "",
    chunks: [
      ["1", "Παῦλος τῇ ἐκκλησίᾳ"],
      ["2", "χάρις ὑμῖν καὶ εἰρήνη"],
      ["3", "εὐχαριστῶ"],
    ],
  },
  "/works/lxx-rahlfs/ps.json": { work_id: "lxx-rahlfs/ps", ref_prefix: "Ps", org_refs: {}, chunks: [["3.2", "κύριε"]] },
  "/works/lat/ep.json": { work_id: "lat/ep", ref_prefix: "", chunks: [["1", "Paulus"]] },
  "/alignments/grc/ep.json": {
    group: "grc/ep",
    pivot: "eng/ep",
    groups: 3,
    members: {
      "eng/ep": { units: 4, spans: "++=+", conf: "999" },
      "grc/ep": { units: 3, spans: "+++", conf: "993" },
    },
  },
};

let ParallelReader: typeof import("./ParallelReader").default;

beforeEach(async () => {
  vi.resetModules();
  ParallelReader = (await import("./ParallelReader")).default;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      const body = Object.entries(files).find(([path]) => url.endsWith(path))?.[1];
      return body ? new Response(JSON.stringify(body)) : new Response("", { status: 404, statusText: "Not Found" });
    }),
  );
  Element.prototype.scrollIntoView = () => {};
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  push.mockClear();
  window.history.replaceState(null, "", "/");
});

const library = (i: LibraryIndex = index): Library => ({ index: i, authors: new Map() });

async function open(lead: typeof kjv, withIds: string[], url = "/", i = index) {
  window.history.replaceState(null, "", url);
  const view = render(<ParallelReader lead={lead} withIds={withIds} library={library(i)} />);
  await vi.waitFor(() => expect(view.container.querySelector("section p")).not.toBeNull());
  return view;
}

describe("ParallelReader: Scripture", () => {
  it("puts the same verse in one row across numberings, each column in its own language and direction", async () => {
    const { container } = await open(kjv, ["oshb/ps", "clementine/ps"]);
    const rows = [...container.querySelectorAll("section > div")];
    const text = (row: Element) => [...row.children].map((c) => c.querySelector("p[id]")?.textContent?.replace(/^\d+/, "") ?? "");
    // The Hebrew title (org 3.1) has no KJV or Vulgate counterpart: empty cells beside it.
    expect(text(rows[0])).toEqual(["", "מִזְמ֥וֹר לְדָוִ֑ד", ""]);
    expect(text(rows[1])).toEqual(["LORD, how are they increased", "יְ֭הוָה מָה־רַבּ֣וּ צָרָ֑י", "Domine, quid multiplicati sunt"]);
    expect(text(rows[2])).toEqual(["My God, my God", "", "Deus, Deus meus"]);
    expect(text(rows[3])).toEqual(["The LORD is my shepherd", "יְהֹוָ֥ה רֹ֝עִ֗י", "Dominus regit me"]);
    const hebrew = rows[3].children[1];
    expect([hebrew.getAttribute("lang"), hebrew.getAttribute("dir")]).toEqual(["hbo", "rtl"]);
    expect([rows[3].children[0].getAttribute("dir"), rows[3].children[2].getAttribute("lang")]).toEqual(["ltr", "la"]);
    // Each column keeps its own numbering; the Vulgate's chapter is named where it differs.
    expect(rows[2].children[2].textContent).toContain("Chapter 21");
    expect(rows[3].children[2].textContent).toContain("Chapter 22");
    // The leading version's ids are its refs; the others' carry their version.
    expect(document.getElementById("Ps.22.1")?.textContent).toContain("My God, my God");
    expect(document.getElementById("Ps.22.1@clementine/ps")?.textContent).toContain("Dominus");
    expect(document.getElementById("Ps.22.1@clementine/ps")?.querySelector("a")?.getAttribute("href")).toBe(
      "#Ps.22.1@clementine/ps",
    );
  });

  // KJV Ps 22:1 and the Vulgate's Ps 22:1 (KJV 23:1) share a ref.
  it("tells a fragment in another version's column from the leading version's same ref", async () => {
    const vulgate = await open(kjv, ["clementine/ps"], "/works/kjv/ps?with=clementine%2Fps#Ps.22.1%40clementine%2Fps");
    await vi.waitFor(() => expect(vulgate.container.querySelector("[data-target]")?.id).toBe("Ps.22.1@clementine/ps"));
    expect(vulgate.container.querySelector("[data-target]")?.textContent).toContain("Dominus regit me");
    cleanup();
    // A plain #ref (search results, the version switcher) is the leading version's.
    const plain = await open(kjv, ["clementine/ps"], "/works/kjv/ps?with=clementine%2Fps#Ps.22.1");
    await vi.waitFor(() => expect(plain.container.querySelector("[data-target]")?.id).toBe("Ps.22.1"));
    expect(plain.container.querySelector("[data-target]")?.textContent).toContain("My God, my God");
    cleanup();
    // A plain ref only another version has is found there.
    const only = await open(kjv, ["clementine/ps"], "/works/kjv/ps?with=clementine%2Fps#Ps.21.1");
    await vi.waitFor(() => expect(only.container.querySelector("[data-target]")?.id).toBe("Ps.21.1@clementine/ps"));
    cleanup();
    // ?nohl scrolls there without marking it.
    const scrolled = await open(kjv, ["clementine/ps"], "/works/kjv/ps?with=clementine%2Fps&nohl#Ps.22.1%40clementine%2Fps");
    expect(scrolled.container.querySelector("[data-target]")).toBeNull();
  });

  it("names each version by language and links its full text, leaving the licence to that page", async () => {
    await open(kjv, ["lxx-rahlfs/ps"]);
    const cards = screen.getByRole("list", { name: "Versions" });
    expect(cards.textContent).toContain("leading");
    expect(cards.textContent).not.toContain("CC BY-NC-SA 4.0");
    expect(cards.textContent).not.toContain("Rahlfs");
    expect(screen.getByRole("link", { name: "Full text: Greek: Rahlfs" }).getAttribute("href")).toBe("/works/lxx-rahlfs/ps");
  });

  it("names the collection only to tell apart two versions in one language", async () => {
    // The cards don't wait for the texts (sinai/ps has none here).
    render(<ParallelReader lead={kjv} withIds={["lxx-rahlfs/ps", "sinai/ps"]} library={library(index)} />);
    const cards = within(await screen.findByRole("list", { name: "Versions" })).getAllByRole("listitem");
    expect(cards.map((c) => c.querySelector("p")?.textContent)).toEqual([
      "Englishleading",
      "Greek · Rahlfs",
      "Greek · Sinai",
    ]);
  });

  it("links to remove, lead with, add a version and go back to one, keeping the URL state", async () => {
    await open(kjv, ["oshb/ps", "clementine/ps"]);
    expect(screen.getByRole("link", { name: "Remove Hebrew: OSHB" }).getAttribute("href")).toBe("/works/kjv/ps?with=clementine%2Fps");
    expect(screen.getByRole("link", { name: "Lead with Latin: Vulgate" }).getAttribute("href")).toBe(
      "/works/clementine/ps?with=kjv%2Fps&with=oshb%2Fps",
    );
    expect(screen.getByRole("link", { name: "Rahlfs" }).getAttribute("href")).toBe(
      "/works/kjv/ps?with=oshb%2Fps&with=clementine%2Fps&with=lxx-rahlfs%2Fps",
    );
    expect(screen.getByRole("link", { name: "Back to reading one version" }).getAttribute("href")).toBe("/works/kjv/ps");
  });

  it("keeps the place when going back to one version", async () => {
    const { container } = await open(kjv, ["oshb/ps"]);
    vi.spyOn(Element.prototype, "getBoundingClientRect").mockImplementation(function (this: Element) {
      const boxes: Record<string, [number, number]> = {
        "s-3": [-300, -200],
        "Ps.3.1": [-260, -210],
        "s-22": [-200, -10],
        "Ps.22.1": [-60, -10],
        "s-23": [-10, 600],
        "Ps.23.1": [-10, 40],
      };
      const [top, bottom] = boxes[this.id] ?? (this.contains(container.querySelector("section")) ? [-100, 900] : [0, 0]);
      return { top, bottom } as DOMRect;
    });
    act(() => screen.getByRole("link", { name: "Back to reading one version" }).click());
    await vi.waitFor(() => expect(push).toHaveBeenCalledWith("/works/kjv/ps?nohl#Ps.23.1"));
    vi.restoreAllMocks();
  });

  it("keeps a passage in another version's column through every control", async () => {
    const { container } = await open(kjv, ["oshb/ps", "clementine/ps"]);
    // At the top of the viewport: the Hebrew Ps 23:1; the KJV's verse beside it starts above.
    vi.spyOn(Element.prototype, "getBoundingClientRect").mockImplementation(function (this: Element) {
      const boxes: Record<string, [number, number]> = {
        "s-3": [-300, -200],
        "s-22": [-200, -10],
        "s-23": [-10, 600],
        "Ps.23.1": [-60, -5],
        "Ps.23.1@oshb/ps": [-5, 30],
      };
      const [top, bottom] = boxes[this.id] ?? (this.contains(container.querySelector("section")) ? [-100, 900] : [0, 0]);
      return { top, bottom } as DOMRect;
    });
    const click = async (name: string, url: string) => {
      push.mockClear();
      act(() => screen.getByRole("link", { name }).click());
      await vi.waitFor(() => expect(push).toHaveBeenCalledWith(url));
    };
    // Still shown: the same passage in its column.
    await click("Remove Latin: Vulgate", "/works/kjv/ps?with=oshb%2Fps&nohl#Ps.23.1%40oshb%2Fps");
    await click("Lead with Latin: Vulgate", "/works/clementine/ps?with=kjv%2Fps&with=oshb%2Fps&nohl#Ps.23.1%40oshb%2Fps");
    await click("Lead with Hebrew: OSHB", "/works/oshb/ps?with=kjv%2Fps&with=clementine%2Fps&nohl#Ps.23.1");
    // No longer shown: mapped from the Hebrew to the leading version.
    await click("Remove Hebrew: OSHB", "/works/kjv/ps?with=clementine%2Fps&nohl#Ps.23.1");
    await click("Back to reading one version", "/works/kjv/ps?nohl#Ps.23.1");
    vi.restoreAllMocks();
  });

  it("keeps a highlighted passage in another version's column highlighted", async () => {
    const { container } = await open(kjv, ["clementine/ps"], "/works/kjv/ps?with=clementine%2Fps#Ps.22.1%40clementine%2Fps");
    await vi.waitFor(() => expect(container.querySelector("[data-target]")).not.toBeNull());
    vi.spyOn(Element.prototype, "getBoundingClientRect").mockImplementation(function (this: Element) {
      const [top, bottom] = this.id === "Ps.22.1@clementine/ps" ? [100, 130] : [-100, 900];
      return { top, bottom } as DOMRect;
    });
    act(() => screen.getByRole("link", { name: "Back to reading one version" }).click());
    await vi.waitFor(() => expect(push).toHaveBeenCalledWith("/works/kjv/ps#Ps.23.1"));
    vi.restoreAllMocks();
  });

  it("explains versions it leaves out", async () => {
    await open(kjv, ["nope/ps", "eng/ep", "oshb/ps", "clementine/ps", "lxx-rahlfs/ps", "sinai/ps"]);
    const notice = screen.getByRole("status");
    expect(notice.textContent).toContain("nope/ps is not in the library.");
    expect(notice.textContent).toContain("eng/ep is not a version of this work.");
    expect(notice.textContent).toContain("sinai/ps is left out: at most 4 versions");
  });
});

describe("ParallelReader: aligned works", () => {
  it("builds rows from the passage alignment, n:m, and marks uncertain passages", async () => {
    const { container } = await open(engEp, ["grc/ep", "lat/ep"]);
    const rows = [...container.querySelectorAll("section > div")];
    expect(rows).toHaveLength(3);
    // The English paragraph 2 is two derived verses beside one Greek paragraph.
    expect(rows[1].children[0].querySelectorAll("[data-target], a[title]")).toHaveLength(2);
    expect(rows[1].children[1].textContent).toContain("χάρις");
    // The Greek span in group 2 is flagged (confidence 3).
    expect(rows[2].hasAttribute("data-uncertain")).toBe(true);
    expect(rows[2].children[1].textContent).toContain("uncertain alignment");
    expect(rows[2].children[0].textContent).not.toContain("uncertain alignment");
    // The Latin isn't in the alignment file: left out, and said so.
    expect(screen.getByRole("status").textContent).toContain("Not aligned with this version yet");
  });

  it("says so when the library has no alignment for the group (published before them)", async () => {
    window.history.replaceState(null, "", "/");
    render(<ParallelReader lead={engEp} withIds={["grc/ep"]} library={library({ ...index, alignments: undefined })} />);
    expect(await screen.findByText(/have no passage alignment yet/)).toBeDefined();
  });
});
