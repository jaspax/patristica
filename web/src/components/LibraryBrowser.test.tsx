import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { AuthorsFile, LibraryIndex, WorkRow } from "@/lib/library";
import { person } from "@/lib/testFixtures";

const replace = vi.fn();
let search = "";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace }),
  usePathname: () => "/works",
  useSearchParams: () => new URLSearchParams(search),
}));

function row(overrides: Partial<WorkRow>): WorkRow {
  return {
    id: "x",
    author: null,
    author_ids: [],
    title: "Untitled",
    language: "lat",
    genre: "patristic",
    tradition: null,
    date: null,
    date_range: null,
    date_confidence: "uncertain",
    source_id: "pta",
    edition: null,
    license: "unknown",
    provenance_url: null,
    translation_of: null,
    chunks: 1,
    file: "works/x.json",
    ...overrides,
  };
}

const index: LibraryIndex = {
  version: "0123456789abcdef",
  sources: { pta: "Patristic Text Archive" },
  works: [
    row({ id: "aug/conf", author: "Augustinus", author_ids: ["augustine-of-hippo"], title: "Confessiones", date: 397 }),
    row({ id: "bas/ep", author: "Basilius", author_ids: ["basil-of-caesarea"], title: "Epistulae", language: "grc", date: 370 }),
  ],
};

const authorsFile: AuthorsFile = {
  authors: [
    person({ id: "augustine-of-hippo", name: "Augustine of Hippo", aliases: ["Augustinus"] }),
    person({ id: "basil-of-caesarea", name: "Basil of Caesarea", aliases: ["Basilius", "Basilius Magnus"] }),
  ],
};

/** Serve index.json (`works`) and authors.json from the fake library. */
function serve(works: LibraryIndex) {
  return vi.fn(async (url: string) =>
    new Response(JSON.stringify(url.endsWith("/authors.json") ? authorsFile : works)),
  );
}

// lib/library caches the index per page session; reload the modules for each test.
let LibraryBrowser: typeof import("./LibraryBrowser").default;

beforeEach(async () => {
  vi.resetModules();
  LibraryBrowser = (await import("./LibraryBrowser")).default;
  search = "";
  replace.mockClear();
  vi.stubGlobal("fetch", serve(index));
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("LibraryBrowser", () => {
  it("lists every work with links to the reader", async () => {
    render(<LibraryBrowser />);
    expect(await screen.findByText("2 works")).toBeDefined();
    const link = screen.getByRole("link", { name: "Confessiones" });
    expect(link.getAttribute("href")).toBe("/works/aug/conf");
  });

  it("applies the filters from the URL", async () => {
    search = "language=grc";
    render(<LibraryBrowser />);
    expect(await screen.findByText(/1 of 2 works/)).toBeDefined();
    expect(screen.queryByText("Confessiones")).toBeNull();
    expect(screen.getByText("Epistulae")).toBeDefined();
  });

  it("writes searches and sorting to the URL", async () => {
    render(<LibraryBrowser />);
    fireEvent.change(await screen.findByRole("searchbox"), { target: { value: "basil" } });
    expect(replace).toHaveBeenLastCalledWith("/works?q=basil", { scroll: false });

    fireEvent.click(screen.getByRole("button", { name: /Date/ }));
    expect(replace).toHaveBeenLastCalledWith("/works?sort=date", { scroll: false });
  });

  it("offers each genre present, apocrypha included, in the genre facet", async () => {
    const apocrypha = row({ id: "anf/protev", title: "Protevangelium", genre: "apocrypha" });
    const withApocrypha = { ...index, works: [...index.works, apocrypha] };
    vi.stubGlobal("fetch", serve(withApocrypha));
    render(<LibraryBrowser />);
    await screen.findByText("3 works");
    const genre = screen.getByRole("combobox", { name: "Genre" });
    const options = [...genre.querySelectorAll("option")].map((o) => [o.value, o.textContent]);
    expect(options).toEqual([
      ["", "All"],
      ["apocrypha", "Apocrypha"],
      ["patristic", "Patristic"],
    ]);
  });

  it("offers authors by id with work counts, and an Anonymous value", async () => {
    const anon = row({ id: "anon/hymn", title: "Hymnus" });
    vi.stubGlobal("fetch", serve({ ...index, works: [...index.works, anon] }));
    render(<LibraryBrowser />);
    await screen.findByText("3 works");
    const author = screen.getByRole("combobox", { name: "Author" });
    const options = [...author.querySelectorAll("option")].map((o) => [o.value, o.textContent]);
    expect(options).toEqual([
      ["", "All"],
      ["anonymous", "Anonymous (1)"],
      ["augustine-of-hippo", "Augustine of Hippo (1)"],
      ["basil-of-caesarea", "Basil of Caesarea (1)"],
    ]);

    fireEvent.change(author, { target: { value: "basil-of-caesarea" } });
    expect(replace).toHaveBeenLastCalledWith("/works?author=basil-of-caesarea", { scroll: false });
  });

  it("filters by the author in the URL and links names to author pages", async () => {
    search = "author=augustine-of-hippo";
    render(<LibraryBrowser />);
    expect(await screen.findByText(/1 of 2 works/)).toBeDefined();
    expect(screen.queryByText("Epistulae")).toBeNull();
    const link = screen.getByRole("link", { name: "Augustine of Hippo" });
    expect(link.getAttribute("href")).toBe("/authors/augustine-of-hippo");
  });

  it("finds an author by a Latin alias", async () => {
    search = "q=magnus";
    render(<LibraryBrowser />);
    expect(await screen.findByText(/1 of 2 works/)).toBeDefined();
    expect(screen.getByRole("link", { name: "Basil of Caesarea" })).toBeDefined();
  });

  it("explains how to export the library when it is missing", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("", { status: 404, statusText: "Not Found" })));
    render(<LibraryBrowser />);
    expect(await screen.findByRole("alert")).toBeDefined();
    expect(screen.getByText(/export_library/)).toBeDefined();
  });
});
