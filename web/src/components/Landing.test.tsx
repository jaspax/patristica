import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { LibraryIndex, WorkRow } from "@/lib/library";

import Landing, { Hero, libraryStats } from "./Landing";

const loadIndex = vi.fn<() => Promise<LibraryIndex>>(() => new Promise(() => {}));
vi.mock("@/lib/library", () => ({ loadIndex: () => loadIndex() }));

afterEach(cleanup);

function row(id: string, language: string, author_ids: string[], chunks: number): WorkRow {
  return {
    id,
    author: null,
    author_ids,
    title: id,
    language,
    genre: "patristic",
    tradition: null,
    date: null,
    date_range: null,
    date_confidence: "uncertain",
    source_id: "pta",
    edition: null,
    license: "public-domain",
    provenance_url: null,
    translation_of: null,
    version_group: null,
    chunks,
    file: `${id}.json`,
  };
}

const index: LibraryIndex = {
  version: "v",
  sources: {},
  works: [
    row("pta/a", "grc", ["basil"], 10),
    row("pta/b", "lat", ["basil", "jerome"], 5),
    row("pta/c", "grc", [], 2),
  ],
};

describe("Hero", () => {
  it("says what Patristica is in the page's heading and lead", () => {
    render(<Hero />);
    expect(screen.getByRole("heading", { level: 1 }).textContent).toMatch(/first thousand years/);
    expect(screen.getByText(/Patristica is a free library/)).toBeTruthy();
  });
});

describe("libraryStats", () => {
  it("counts works, distinct authors and languages, and passages", () => {
    expect(libraryStats(index)).toEqual([
      { label: "works", value: 3 },
      { label: "authors", value: 2 },
      { label: "languages", value: 2 },
      { label: "passages", value: 17 },
    ]);
  });
});

describe("Landing", () => {
  it("links each example to its search", () => {
    render(<Landing />);
    const link = screen.getByRole("link", { name: "baptism of desire" });
    expect(link.getAttribute("href")).toBe("/?q=baptism+of+desire");
  });

  it("links the Word in each script to the library filtered to its language", () => {
    render(<Landing />);
    const strip = screen.getByRole("region", { name: /In the beginning was the Word/ });
    const greek = within(strip).getByRole("link", { name: /λόγος/ });
    expect(greek.getAttribute("href")).toBe("/works?language=grc");
    expect(greek.querySelector("[lang]")?.getAttribute("lang")).toBe("grc");
    const slavonic = within(strip).getByRole("link", { name: /слово/ });
    expect(slavonic.getAttribute("href")).toBe("/works?language=chu");
    expect(slavonic.querySelector("[lang]")?.getAttribute("lang")).toBe("cu");
    const arabic = within(strip).getByRole("link", { name: /الكلمة/ });
    expect(arabic.getAttribute("href")).toBe("/works?language=arb");
    expect(arabic.querySelector("[lang]")?.getAttribute("lang")).toBe("ar");
    expect(arabic.querySelector("[lang]")?.getAttribute("dir")).toBe("rtl");
    const georgian = within(strip).getByRole("link", { name: /სიტყუაჲ/ });
    expect(georgian.getAttribute("href")).toBe("/works?language=oge");
    expect(georgian.querySelector("[lang]")?.getAttribute("lang")).toBe("oge");
    expect(georgian.querySelector("[lang]")?.getAttribute("dir")).toBe("ltr");
    const irish = within(strip).getByRole("link", { name: /bríathar/ });
    expect(irish.getAttribute("href")).toBe("/works?language=sga");
    expect(irish.querySelector("[lang]")?.getAttribute("lang")).toBe("sga");
    expect(irish.querySelector("[lang]")?.getAttribute("dir")).toBe("ltr");
    expect(within(strip).getAllByRole("link")).toHaveLength(12);
  });

  it("shows the library's counts once the index loads", async () => {
    loadIndex.mockResolvedValueOnce(index);
    render(<Landing />);
    expect(await screen.findByText("17", { selector: ".visually-hidden" })).toBeTruthy();
  });
});
