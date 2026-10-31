import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { AuthorsFile, LibraryIndex } from "@/lib/library";
import { person, workRow } from "@/lib/testFixtures";

let params: { id: string } = { id: "john-chrysostom" };
let search = "";
const replace = vi.fn();

vi.mock("next/navigation", () => ({
  useParams: () => params,
  usePathname: () => `/authors/${params.id}`,
  useRouter: () => ({ replace }),
  useSearchParams: () => new URLSearchParams(search),
}));

const index: LibraryIndex = {
  version: "0123456789abcdef",
  sources: { first1k: "First1KGreek", npnf1: "NPNF I" },
  works: [
    workRow({ id: "first1k/sac", author_ids: ["john-chrysostom"], title: "De sacerdotio", language: "grc", source_id: "first1k", date: 390, date_confidence: "approximate" }),
    workRow({ id: "npnf1/mt", author_ids: ["john-chrysostom"], title: "Homilies on Matthew", language: "eng", source_id: "npnf1" }),
    workRow({ id: "pl/op", author_ids: ["pseudo-chrysostom"], title: "Opus imperfectum", language: "lat" }),
    workRow({ id: "pl/hier", author_ids: ["jerome"], title: "De viris illustribus", language: "lat" }),
  ],
};

const authors: AuthorsFile = {
  authors: [
    person({
      id: "john-chrysostom",
      name: "John Chrysostom",
      aliases: ["Joannes Chrysostomus"],
      birth: { low: 347, high: 349, confidence: "approximate" },
      death: { low: 407, high: 407, confidence: "established" },
      tradition: "greek",
    }),
    person({ id: "pseudo-chrysostom", name: "Pseudo-Chrysostom", pseudo_of: "john-chrysostom" }),
    person({
      id: "jerome",
      name: "Jerome",
      floruit: { low: 370, high: 420, confidence: "uncertain" },
    }),
  ],
};

let AuthorPage: typeof import("./AuthorPage").default;

beforeEach(async () => {
  vi.resetModules();
  AuthorPage = (await import("./AuthorPage")).default;
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

describe("AuthorPage", () => {
  it("shows the author's dates, with their certainty, and tradition", async () => {
    params = { id: "john-chrysostom" };
    render(<AuthorPage />);
    expect(await screen.findByRole("heading", { level: 1, name: "John Chrysostom" })).toBeDefined();
    expect(screen.getByText("c. 347–349")).toBeDefined();
    expect(screen.getByText("407")).toBeDefined();
    expect(screen.getByText("Tradition").nextElementSibling?.textContent).toBe("Greek");
    expect(screen.getByText("Joannes Chrysostomus")).toBeDefined();
  });

  it("lists the works grouped by language, with links to the reader", async () => {
    params = { id: "john-chrysostom" };
    render(<AuthorPage />);
    expect(await screen.findByRole("heading", { name: /^2 works/ })).toBeDefined();
    const groups = screen.getAllByRole("region").filter((r) => r.hasAttribute("aria-label"));
    expect(groups.map((g) => g.getAttribute("aria-label"))).toEqual(["English", "Greek"]);
    const greek = within(groups[1]).getByRole("link", { name: "De sacerdotio" });
    expect(greek.getAttribute("href")).toBe("/works/first1k/sac");
    expect(within(groups[1]).getByText(/First1KGreek · c\. 390/)).toBeDefined();
    expect(screen.queryByText("Opus imperfectum")).toBeNull();
    const browse = screen.getByRole("link", { name: /Filter the library/ });
    expect(browse.getAttribute("href")).toBe("/works?author=john-chrysostom");
  });

  it("filters the works like the library, without an author facet", async () => {
    params = { id: "john-chrysostom" };
    render(<AuthorPage />);
    const form = await screen.findByRole("search", { name: "Filter John Chrysostom's works" });
    expect(within(form).queryByText("Author")).toBeNull();
    expect(within(form).getByText("Language")).toBeDefined();
    // Only the collections the author's works are in.
    const collections = within(form).getByRole("combobox", { name: "Collection" });
    expect([...collections.querySelectorAll("option")].map((o) => o.textContent)).toEqual(["All", "First1KGreek", "NPNF I"]);
    fireEvent.change(within(form).getByRole("searchbox"), { target: { value: "matthew" } });
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/authors/john-chrysostom?q=matthew", { scroll: false }));
  });

  it("reads the filters from the URL and counts what they leave", async () => {
    params = { id: "john-chrysostom" };
    search = "language=grc";
    render(<AuthorPage />);
    expect(await screen.findByText(/^1 of 2 works/)).toBeDefined();
    expect(screen.queryByText("Homilies on Matthew")).toBeNull();
    expect(screen.getByRole("link", { name: "De sacerdotio" })).toBeDefined();
    // The library link keeps the filters.
    const browse = screen.getByRole("link", { name: /Filter the library/ });
    expect(browse.getAttribute("href")).toBe("/works?author=john-chrysostom&language=grc");
    fireEvent.click(screen.getByRole("button", { name: "Clear filters" }));
    expect(replace).toHaveBeenCalledWith("/authors/john-chrysostom", { scroll: false });
  });

  it("links pseudonymous authors both ways", async () => {
    params = { id: "john-chrysostom" };
    render(<AuthorPage />);
    const pseudo = await screen.findByRole("link", { name: "Pseudo-Chrysostom" });
    expect(pseudo.getAttribute("href")).toBe("/authors/pseudo-chrysostom");
    cleanup();

    params = { id: "pseudo-chrysostom" };
    render(<AuthorPage />);
    const real = await screen.findByRole("link", { name: "John Chrysostom" });
    expect(real.getAttribute("href")).toBe("/authors/john-chrysostom");
    expect(screen.getByText("No dates are recorded for this author.")).toBeDefined();
  });

  it("marks an uncertain floruit", async () => {
    params = { id: "jerome" };
    render(<AuthorPage />);
    expect(await screen.findByText("fl. 370–420?")).toBeDefined();
  });

  it("says when the author id is unknown", async () => {
    params = { id: "nobody" };
    render(<AuthorPage />);
    expect(await screen.findByRole("heading", { name: "Author not found" })).toBeDefined();
  });
});
