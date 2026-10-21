import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { AuthorsFile, LibraryIndex } from "@/lib/library";
import { person, workRow } from "@/lib/testFixtures";

let search = "";
const replace = vi.fn();

vi.mock("next/navigation", () => ({
  usePathname: () => "/authors",
  useRouter: () => ({ replace }),
  useSearchParams: () => new URLSearchParams(search),
}));

const index: LibraryIndex = {
  version: "0123456789abcdef",
  sources: { first1k: "First1KGreek", npnf1: "NPNF I", pl: "PL" },
  works: [
    workRow({ id: "first1k/sac", author_ids: ["john-chrysostom"], title: "De sacerdotio", language: "grc", source_id: "first1k" }),
    workRow({ id: "npnf1/mt", author_ids: ["john-chrysostom"], title: "Homilies on Matthew", language: "eng", source_id: "npnf1" }),
    workRow({ id: "npnf1/conf", author_ids: ["augustine-of-hippo"], title: "Confessions", language: "eng", source_id: "npnf1" }),
    workRow({ id: "pl/hier", author_ids: ["jerome"], title: "De viris illustribus", language: "lat", source_id: "pl" }),
  ],
};

const authors: AuthorsFile = {
  authors: [
    person({ id: "augustine-of-hippo", name: "Augustine of Hippo", aliases: ["Augustinus"] }),
    person({ id: "jerome", name: "Jerome", aliases: ["Hieronymus"] }),
    person({ id: "john-chrysostom", name: "John Chrysostom" }),
  ],
};

let AuthorList: typeof import("./AuthorList").default;

beforeEach(async () => {
  vi.resetModules();
  AuthorList = (await import("./AuthorList")).default;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => new Response(JSON.stringify(url.endsWith("/authors.json") ? authors : index))),
  );
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  search = "";
  replace.mockReset();
});

/** [name, works] per table row. */
function rows(): [string, string][] {
  return within(screen.getAllByRole("rowgroup")[1])
    .getAllByRole("row")
    .map((r) => {
      const cells = within(r).getAllByRole("cell");
      return [cells[0].textContent ?? "", cells[3].textContent ?? ""];
    });
}

describe("AuthorList", () => {
  it("offers the library's facets, without an author facet", async () => {
    render(<AuthorList />);
    const form = await screen.findByRole("search");
    for (const label of ["Language", "Genre", "Collection"]) expect(within(form).getByText(label)).toBeDefined();
    expect(within(form).queryByText("Author")).toBeNull();
    expect(rows()).toEqual([
      ["Augustine of Hippo", "1"],
      ["Jerome", "1"],
      ["John Chrysostom", "2"],
    ]);
  });

  it("lists the authors with works the facets leave, counting only those", async () => {
    search = "language=eng";
    render(<AuthorList />);
    expect(await screen.findByText(/^2 of 3 authors with matching works/)).toBeDefined();
    expect(rows()).toEqual([
      ["Augustine of Hippo", "1"],
      ["John Chrysostom", "1"],
    ]);
    // An author's page opens with the same facets.
    expect(screen.getByRole("link", { name: "John Chrysostom" }).getAttribute("href")).toBe(
      "/authors/john-chrysostom?language=eng",
    );
    fireEvent.click(screen.getByRole("button", { name: "Clear filters" }));
    expect(replace).toHaveBeenCalledWith("/authors", { scroll: false });
  });

  it("searches names and aliases from the URL, and writes the query back", async () => {
    search = "q=hieronymus";
    render(<AuthorList />);
    await screen.findByRole("search");
    expect(rows()).toEqual([["Jerome", "1"]]);
    expect(screen.getByRole("link", { name: "Jerome" }).getAttribute("href")).toBe("/authors/jerome");
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "john" } });
    expect(replace).toHaveBeenCalledWith("/authors?q=john", { scroll: false });
  });
});
