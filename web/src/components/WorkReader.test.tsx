import { act, cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { AlignmentFile, AuthorsFile, LibraryIndex, WorkFile } from "@/lib/library";
import { person, workRow } from "@/lib/testFixtures";

let params: { id: string[] } = { id: ["pl", "both"] };
const push = vi.fn();

vi.mock("next/navigation", () => ({
  useParams: () => params,
  useRouter: () => ({ push }),
  useSearchParams: () => new URLSearchParams(window.location.search),
}));

const index: LibraryIndex = {
  version: "0123456789abcdef",
  sources: {
    pl: "Patrologia Latina",
    oshb: "Open Scriptures Hebrew Bible",
    kjv: "King James Version",
    clementine: "Clementine Vulgate",
    first1k: "First Thousand Years of Greek",
    "npnf-works": "Nicene and Post-Nicene Fathers",
    "mt-eng": "Patristica machine translations",
  },
  works: [
    workRow({ id: "oshb/ps", title: "Psalms", language: "hbo", source_id: "oshb", genre: "scripture", version_group: "book:ps" }),
    workRow({ id: "kjv/ps", title: "Psalms", language: "eng", source_id: "kjv", genre: "scripture", version_group: "book:ps", file: "works/kjv/Ps.json" }),
    workRow({ id: "clementine/ps", title: "Psalms", language: "lat", source_id: "clementine", genre: "scripture", version_group: "book:ps", file: "works/clementine/Ps.json" }),
    workRow({ id: "first1k/hom", title: "Homiliae", language: "grc", source_id: "first1k", version_group: "first1k/hom", file: "works/first1k/hom.json" }),
    workRow({
      id: "npnf-works/hom",
      title: "Homilies",
      language: "eng",
      source_id: "npnf-works",
      translation_of: "first1k/hom",
      version_group: "first1k/hom",
      file: "works/npnf/hom.json",
    }),
    workRow({
      id: "pl/both",
      author: "Hieronymus; Augustinus",
      author_ids: ["jerome", "augustine-of-hippo"],
      title: "Epistulae mutuae",
      source_id: "pl",
      file: "works/pl/both.json",
    }),
    workRow({ id: "pl/acta", author: "Acta Thomae", title: "Acta Thomae", source_id: "pl", file: "works/pl/acta.json" }),
    workRow({ id: "pta/or", title: "Oratio", language: "grc", source_id: "pta", version_group: "pta/or", file: "works/pta/or.json" }),
    workRow({
      id: "mt-eng/pta/or",
      title: "Oration",
      language: "eng",
      source_id: "mt-eng",
      translation_of: "pta/or",
      version_group: "pta/or",
      machine_translation: true,
      file: "works/mt-eng/pta/or.json",
    }),
  ],
  alignments: ["first1k/hom"],
};

const authors: AuthorsFile = {
  authors: [
    person({ id: "jerome", name: "Jerome", aliases: ["Hieronymus"] }),
    person({ id: "augustine-of-hippo", name: "Augustine of Hippo", aliases: ["Augustinus"] }),
  ],
};

const work: WorkFile = { work_id: "pl/both", ref_prefix: "Ep", chunks: [["1", "Salve."]] };
const files: Record<string, WorkFile | AlignmentFile> = {
  "/works/npnf/hom.json": {
    work_id: "npnf-works/hom",
    ref_prefix: "Hom",
    chunks: [["1", "The first homily"], ["2", "The second homily"], ["3", "A translator's note"]],
  },
  "/works/first1k/hom.json": {
    work_id: "first1k/hom",
    ref_prefix: "",
    chunks: [["1.s1", "Ὁμιλία πρώτη."], ["1.s2", "Ἔτι."], ["2", "Ὁμιλία δευτέρα."]],
  },
  "/alignments/first1k/hom.json": {
    group: "first1k/hom",
    pivot: "npnf-works/hom",
    groups: 2,
    members: {
      "npnf-works/hom": { units: 3, spans: "++.", conf: "99" },
      "first1k/hom": { units: 3, spans: "+=+", conf: "99" },
    },
  },
  "/works/kjv/Ps.json": {
    work_id: "kjv/ps",
    ref_prefix: "Ps.23",
    org_refs: {},
    chunks: [["1", "The LORD is my shepherd"], ["2", "He maketh me to lie down"]],
  },
  "/works/clementine/Ps.json": {
    work_id: "clementine/ps",
    ref_prefix: "Ps.22",
    org_refs: { "1": "Ps.23.1", "2": "Ps.23.2" },
    chunks: [["1", "Dominus regit me"], ["2", "in loco pascuae"]],
  },
};

let WorkReader: typeof import("./WorkReader").default;

beforeEach(async () => {
  vi.resetModules();
  WorkReader = (await import("./WorkReader")).default;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      const psalm = Object.entries(files).find(([path]) => url.endsWith(path))?.[1];
      const body = url.endsWith("/authors.json") ? authors : url.endsWith("/index.json") ? index : (psalm ?? work);
      return new Response(JSON.stringify(body));
    }),
  );
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  push.mockClear();
  window.history.replaceState(null, "", "/");
});

describe("WorkReader author line", () => {
  it("links each author to its author page and keeps the source's attribution", async () => {
    params = { id: ["pl", "both"] };
    render(<WorkReader />);
    const jerome = await screen.findByRole("link", { name: "Jerome" });
    expect(jerome.getAttribute("href")).toBe("/authors/jerome");
    const augustine = screen.getByRole("link", { name: "Augustine of Hippo" });
    expect(augustine.getAttribute("href")).toBe("/authors/augustine-of-hippo");
    expect(screen.getByText("Attributed as")).toBeDefined();
    expect(screen.getByText("Hieronymus; Augustinus")).toBeDefined();
  });

  it("shows no author link for an anonymous work", async () => {
    params = { id: ["pl", "acta"] };
    render(<WorkReader />);
    await screen.findByRole("heading", { level: 1, name: "Acta Thomae" });
    expect(screen.queryAllByRole("link").filter((a) => a.getAttribute("href")?.startsWith("/authors/"))).toEqual(
      [],
    );
  });
});

describe("WorkReader header", () => {
  it("puts date, language and genre on one line and folds the rest under Details", async () => {
    params = { id: ["pl", "both"] };
    render(<WorkReader />);
    await screen.findByRole("heading", { level: 1 });
    const facts = screen.getByText("Language", { selector: "dt" }).closest("dl")!;
    expect([...facts.querySelectorAll("dt")].map((dt) => dt.textContent)).toEqual(["Date", "Language", "Genre"]);
    const details = screen.getByText("Details", { selector: "summary" }).closest("details")!;
    expect(details.open).toBe(false);
    for (const label of ["Attributed as", "Collection", "Licence"]) {
      expect(within(details).getByText(label, { selector: "dt" })).toBeDefined();
    }
  });
});

describe("WorkReader versions", () => {
  it("names the original and lists the other versions of a Scripture book", async () => {
    params = { id: ["kjv", "ps"] };
    render(<WorkReader />);
    await screen.findByText("Other versions (2 in 2 languages)");
    expect(screen.getByText("Original", { selector: "dt" })).toBeDefined();
    const originals = screen.getAllByRole("link", { name: /^(Hebrew: )?Open Scriptures Hebrew Bible$/ });
    expect(originals.map((a) => a.textContent)).toEqual(["Hebrew: Open Scriptures Hebrew Bible", "Open Scriptures Hebrew Bible"]);
    expect(originals.every((a) => a.getAttribute("href") === "/works/oshb/ps")).toBe(true);
    expect(screen.getByRole("link", { name: "Clementine Vulgate" }).getAttribute("href")).toBe("/works/clementine/ps");
    // Scripture can always be read side by side (#181).
    expect(screen.getByRole("link", { name: "Read side by side with Clementine Vulgate" }).getAttribute("href")).toBe(
      "/works/kjv/ps?with=clementine%2Fps",
    );
  });

  it("offers side by side reading only where the versions are aligned", async () => {
    params = { id: ["npnf-works", "hom"] };
    render(<WorkReader />);
    await screen.findByText("Other versions (1)");
    expect(screen.getByRole("link", { name: "Read side by side with First Thousand Years of Greek" })).toBeDefined();
    cleanup();
    // A library published before alignments were exported has no list.
    const fetch = globalThis.fetch as unknown as { mockImplementation: (f: (url: string) => Promise<Response>) => void };
    const previous = { ...index, alignments: undefined };
    fetch.mockImplementation(async (url: string) => {
      const file = Object.entries(files).find(([path]) => url.endsWith(path))?.[1];
      const body = url.endsWith("/authors.json") ? authors : url.endsWith("/index.json") ? previous : (file ?? work);
      return new Response(JSON.stringify(body));
    });
    vi.resetModules();
    const Fresh = (await import("./WorkReader")).default;
    render(<Fresh />);
    await screen.findByText("Other versions (1)");
    expect(screen.queryByRole("link", { name: /side by side/ })).toBeNull();
  });

  it("keeps a translation's 'Translation of' line and lists the original", async () => {
    params = { id: ["npnf-works", "hom"] };
    render(<WorkReader />);
    await screen.findByText("Other versions (1)");
    expect(screen.getByText("Translation of")).toBeDefined();
    // The Translation of line replaces the generic Original line.
    expect(screen.queryByText("Original", { selector: "dt" })).toBeNull();
    expect(screen.getByRole("link", { name: "Homiliae" }).getAttribute("href")).toBe("/works/first1k/hom");
  });

  it("opens parallel reading for ?with= (#181)", async () => {
    window.history.replaceState(null, "", "/works/kjv/ps?with=clementine%2Fps");
    params = { id: ["kjv", "ps"] };
    render(<WorkReader />);
    expect(await screen.findByText(/Reading 2 versions side by side/)).toBeDefined();
    expect(await screen.findByText("Dominus regit me")).toBeDefined();
  });

  it("shows no versions control for a work with no other version", async () => {
    params = { id: ["pl", "acta"] };
    render(<WorkReader />);
    await screen.findByRole("heading", { level: 1, name: "Acta Thomae" });
    expect(screen.queryByText(/Other versions/)).toBeNull();
  });

  it("floats the list once the header's list has scrolled off screen", async () => {
    let notify: (entries: Partial<IntersectionObserverEntry>[]) => void = () => {};
    const observed: Element[] = [];
    vi.stubGlobal(
      "IntersectionObserver",
      class {
        constructor(cb: typeof notify) {
          notify = cb;
        }
        observe(el: Element) {
          observed.push(el);
        }
        disconnect() {}
      },
    );
    params = { id: ["kjv", "ps"] };
    render(<WorkReader />);
    const summary = await screen.findByText("Other versions (2 in 2 languages)");
    // The header's list is what is observed; on screen, nothing floats.
    expect(observed).toEqual([summary.closest("details")]);
    expect(screen.queryByRole("button", { name: /Other versions/ })).toBeNull();
    act(() => notify([{ isIntersecting: false }]));
    expect(screen.getByRole("button", { name: "Other versions (2 in 2 languages)" })).toBeDefined();
    act(() => notify([{ isIntersecting: true }]));
    expect(screen.queryByRole("button", { name: /Other versions/ })).toBeNull();
  });
});

describe("WorkReader version switch", () => {
  // jsdom has no layout: put the text above the viewport top and give
  // elements a box by id ([top, bottom]); everything else sits at 0.
  function layout(boxes: Record<string, [number, number]>) {
    vi.spyOn(Element.prototype, "getBoundingClientRect").mockImplementation(function (this: Element) {
      const [top, bottom] = boxes[this.id] ?? (this.tagName === "SECTION" ? [-100, 600] : [0, 0]);
      return { top, bottom } as DOMRect;
    });
    Element.prototype.scrollIntoView = () => {};
  }

  async function openKjv(url: string) {
    window.history.replaceState(null, "", url);
    params = { id: ["kjv", "ps"] };
    const view = render(<WorkReader />);
    await screen.findByText("The LORD is my shepherd");
    return view;
  }

  it("keeps a highlighted passage highlighted", async () => {
    layout({ "Ps.23.1": [100, 130] });
    const { container } = await openKjv("/works/kjv/ps#Ps.23.1");
    // The fragment was highlighted on opening (useHashTarget, in an effect after the text renders).
    await vi.waitFor(() => expect(container.querySelector("[data-target]")?.id).toBe("Ps.23.1"));
    // Its place in the text: the wrapper starts above the viewport.
    container.querySelector("article > div")!.id = "text";
    layout({ "Ps.23.1": [100, 130], text: [-50, 900] });
    act(() => screen.getByRole("link", { name: "Clementine Vulgate" }).click());
    await vi.waitFor(() => expect(push).toHaveBeenCalledWith("/works/clementine/ps#Ps.22.1"));
  });

  it("opens a scroll position without a highlight (?nohl)", async () => {
    const { container } = await openKjv("/works/kjv/ps");
    expect(container.querySelector("[data-target]")).toBeNull();
    container.querySelector("article > div")!.id = "text";
    layout({ text: [-400, 900], "Ps.23.1": [-40, -5], "Ps.23.2": [-5, 30] });
    act(() => screen.getByRole("link", { name: "Clementine Vulgate" }).click());
    await vi.waitFor(() => expect(push).toHaveBeenCalledWith("/works/clementine/ps?nohl#Ps.22.2"));
  });

  async function openHomilies(url: string) {
    window.history.replaceState(null, "", url);
    params = { id: ["npnf-works", "hom"] };
    const view = render(<WorkReader />);
    await screen.findByText("The second homily");
    view.container.querySelector("article > div")!.id = "text";
    return view;
  }

  it("keeps the place in other works through the passage alignment (#179)", async () => {
    const { container } = await openHomilies("/works/npnf-works/hom#Hom.2");
    // useHashTarget marks the fragment in an effect after the text renders: wait for it,
    // or the click can read the position before it is marked (and open it with ?nohl).
    await vi.waitFor(() => expect(container.querySelector("[data-target]")?.id).toBe("Hom.2"));
    layout({ "Hom.2": [100, 130], text: [-50, 900] });
    act(() => screen.getByRole("link", { name: "First Thousand Years of Greek" }).click());
    await vi.waitFor(() => expect(push).toHaveBeenCalledWith("/works/first1k/hom#2"));
  });

  it("doesn't highlight a nearby passage it falls back to", async () => {
    // The translator's note is in no alignment group: open the passage before it, unmarked.
    const { container } = await openHomilies("/works/npnf-works/hom#Hom.3");
    await vi.waitFor(() => expect(container.querySelector("[data-target]")?.id).toBe("Hom.3"));
    layout({ "Hom.3": [100, 130], text: [-50, 900] });
    act(() => screen.getByRole("link", { name: "First Thousand Years of Greek" }).click());
    await vi.waitFor(() => expect(push).toHaveBeenCalledWith("/works/first1k/hom?nohl#2"));
  });
});

describe("WorkReader machine translation (#422)", () => {
  it("marks a machine translation and links the original it was made from", async () => {
    params = { id: ["mt-eng", "pta", "or"] };
    render(<WorkReader />);
    await screen.findByRole("heading", { level: 1, name: "Oration" });
    expect(screen.getAllByText("Machine translation").length).toBeGreaterThan(0);
    const notice = screen.getByRole("note", { name: "Machine translation" });
    expect(notice.textContent).toBe(
      "This English text was machine-translated from the Greek original by an AI model and has not been " +
        "reviewed. It may contain errors; consult the original for close study.",
    );
    expect(within(notice).getByRole("link", { name: "Greek original" }).getAttribute("href")).toBe("/works/pta/or");
  });

  it("shows no notice on other works", async () => {
    params = { id: ["pta", "or"] };
    render(<WorkReader />);
    await screen.findByRole("heading", { level: 1, name: "Oratio" });
    expect(screen.queryByRole("note")).toBeNull();
    // The other version is still badged in the version list.
    expect(screen.getByText("Machine translation")).toBeDefined();
  });
});
