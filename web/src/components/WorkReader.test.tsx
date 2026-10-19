import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { AuthorsFile, LibraryIndex, WorkFile } from "@/lib/library";
import { person, workRow } from "@/lib/testFixtures";

let params: { id: string[] } = { id: ["pl", "both"] };

vi.mock("next/navigation", () => ({
  useParams: () => params,
  useRouter: () => ({ push: vi.fn() }),
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
  },
  works: [
    workRow({ id: "oshb/ps", title: "Psalms", language: "hbo", source_id: "oshb", genre: "scripture", version_group: "book:ps" }),
    workRow({ id: "kjv/ps", title: "Psalms", language: "eng", source_id: "kjv", genre: "scripture", version_group: "book:ps" }),
    workRow({ id: "clementine/ps", title: "Psalms", language: "lat", source_id: "clementine", genre: "scripture", version_group: "book:ps" }),
    workRow({ id: "first1k/hom", title: "Homiliae", language: "grc", source_id: "first1k", version_group: "first1k/hom" }),
    workRow({
      id: "npnf-works/hom",
      title: "Homilies",
      language: "eng",
      source_id: "npnf-works",
      translation_of: "first1k/hom",
      version_group: "first1k/hom",
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
  ],
};

const authors: AuthorsFile = {
  authors: [
    person({ id: "jerome", name: "Jerome", aliases: ["Hieronymus"] }),
    person({ id: "augustine-of-hippo", name: "Augustine of Hippo", aliases: ["Augustinus"] }),
  ],
};

const work: WorkFile = { work_id: "pl/both", ref_prefix: "Ep", chunks: [["1", "Salve."]] };

let WorkReader: typeof import("./WorkReader").default;

beforeEach(async () => {
  vi.resetModules();
  WorkReader = (await import("./WorkReader")).default;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      const body = url.endsWith("/authors.json") ? authors : url.endsWith("/index.json") ? index : work;
      return new Response(JSON.stringify(body));
    }),
  );
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
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

describe("WorkReader versions", () => {
  it("names the original and lists the other versions of a Scripture book", async () => {
    params = { id: ["kjv", "ps"] };
    render(<WorkReader />);
    await screen.findByText("Other versions (2 in 2 languages)");
    expect(screen.getByText("Original", { selector: "dt" })).toBeDefined();
    const originals = screen.getAllByRole("link", { name: /Open Scriptures Hebrew Bible/ });
    expect(originals.map((a) => a.textContent)).toEqual(["Hebrew: Open Scriptures Hebrew Bible", "Open Scriptures Hebrew Bible"]);
    expect(originals.every((a) => a.getAttribute("href") === "/works/oshb/ps")).toBe(true);
    expect(screen.getByRole("link", { name: "Clementine Vulgate" }).getAttribute("href")).toBe("/works/clementine/ps");
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

  it("shows no versions control for a work with no other version", async () => {
    params = { id: ["pl", "acta"] };
    render(<WorkReader />);
    await screen.findByRole("heading", { level: 1, name: "Acta Thomae" });
    expect(screen.queryByText(/Other versions/)).toBeNull();
  });
});
