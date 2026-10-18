import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { AuthorsFile, LibraryIndex } from "@/lib/library";
import type { SearchResponse, SearchResult } from "@/lib/search";
import { person, workRow } from "@/lib/testFixtures";

const push = vi.fn();
let search = "";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push }),
  usePathname: () => "/search",
  useSearchParams: () => new URLSearchParams(search),
}));

const index: LibraryIndex = {
  version: "0123456789abcdef",
  sources: { pta: "Patristic Text Archive", kjv: "King James Version" },
  works: [
    workRow({ id: "pta/hymns", author_ids: ["ephrem-the-syrian"], language: "syc", source_id: "pta" }),
    workRow({ id: "kjv/gen", language: "eng", genre: "scripture", source_id: "kjv" }),
  ],
};

const authorsFile: AuthorsFile = {
  authors: [person({ id: "ephrem-the-syrian", name: "Ephrem the Syrian" })],
};

function result(overrides: Partial<SearchResult> = {}): SearchResult {
  return {
    chunk_id: "pta/hymns#Hymn.1.1",
    work_id: "pta/hymns",
    canonical_ref: "Hymn.1.1",
    language: "syc",
    text: "ܗܝܡܢܘܬܐ ܕܝܠܢ ܫܪܝܪܬܐ",
    text_truncated: false,
    translation: { language: "eng", text: "Our faith is true.", model: "gpt-6.1-sol", machine: true },
    score: 0.71,
    matched: "translation",
    date_composed: 360,
    date_range: [350, 373],
    out_of_period: false,
    citation: "Ephrem the Syrian, *Hymns on Faith* Hymn.1.1",
    work: {
      title: "Hymns on Faith",
      authors: [{ id: "ephrem-the-syrian", name: "Ephrem the Syrian" }],
      genre: "patristic",
      tradition: "syriac",
      date_composed: 360,
      date_range: [350, 373],
      edition: "PTA",
      source_label: "Patristic Text Archive",
      license: "cc-by-sa-4.0",
      provenance_url: "https://example.org/hymns",
    },
    ...overrides,
  };
}

function page(results: SearchResult[], overrides: Partial<SearchResponse> = {}): SearchResponse {
  return {
    query: "faith",
    mode: "vector",
    requested_mode: "vector",
    offset: 0,
    limit: 20,
    next_offset: null,
    results,
    ...overrides,
  };
}

/** Serve the library files, and `api` for /api/search requests (by offset). */
function serve(api: (url: URL) => Response) {
  const fetch = vi.fn(async (input: string) => {
    const url = new URL(input, "http://localhost");
    if (url.pathname === "/api/search") return api(url);
    return new Response(JSON.stringify(url.pathname.endsWith("/authors.json") ? authorsFile : index));
  });
  vi.stubGlobal("fetch", fetch);
  return fetch;
}

const json = (body: unknown, status = 200, headers: Record<string, string> = {}) =>
  new Response(JSON.stringify(body), { status, headers });

async function renderPage() {
  const { default: SearchPage } = await import("./SearchPage");
  return render(<SearchPage />);
}

beforeEach(() => {
  push.mockReset();
  search = "";
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("SearchPage", () => {
  it("explains search when there is no query, and sends no request", async () => {
    const fetch = serve(() => json(page([])));
    await renderPage();
    expect(screen.getByText(/Search by meaning/)).toBeTruthy();
    expect(fetch.mock.calls.some(([u]) => String(u).startsWith("/api/"))).toBe(false);
  });

  it("puts the query and filters in the URL", async () => {
    serve(() => json(page([])));
    await renderPage();
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "  faith  " } });
    fireEvent.submit(screen.getByRole("search"));
    expect(push).toHaveBeenCalledWith("/search?q=faith", { scroll: false });

    fireEvent.change(await screen.findByLabelText("Language"), { target: { value: "syc" } });
    expect(push).toHaveBeenLastCalledWith("/search?language=syc", { scroll: false });
  });

  it("renders results with the citation first, the text in its script and the translation labelled", async () => {
    search = "q=faith&language=syc";
    const fetch = serve(() => json(page([result()])));
    await renderPage();
    const item = (await screen.findAllByRole("listitem"))[0];
    expect(fetch.mock.calls.map(([u]) => String(u))).toContain("/api/search?q=faith&language=syc&limit=20");

    const link = within(item).getByRole("link", { name: /Hymns on Faith Hymn\.1\.1/ });
    expect(link.getAttribute("href")).toBe("/works/pta/hymns#Hymn.1.1");
    expect(within(item).getByRole("link", { name: "Ephrem the Syrian" }).getAttribute("href")).toBe(
      "/authors/ephrem-the-syrian",
    );
    const text = within(item).getByText("ܗܝܡܢܘܬܐ ܕܝܠܢ ܫܪܝܪܬܐ");
    expect(text.getAttribute("lang")).toBe("syc");
    expect(text.getAttribute("dir")).toBe("rtl");
    expect(within(item).getByText("Machine translation (English)")).toBeTruthy();
    expect(within(item).getByText("Our faith is true.").getAttribute("lang")).toBe("en");
    expect(within(item).getByText(/350–373 · Patristic Text Archive, PTA/)).toBeTruthy();
    expect(within(item).getByRole("link", { name: "CC BY-SA 4.0" })).toBeTruthy();
    expect(item.textContent).not.toContain("pta/hymns");
  });

  it("names the collection once when the edition includes it", async () => {
    search = "q=light";
    serve(() =>
      json(
        page([
          result({
            language: "eng",
            translation: null,
            work: { ...result().work, source_label: "King James Version", edition: "King James Version (1769)" },
          }),
        ]),
      ),
    );
    await renderPage();
    expect(await screen.findByText(/350–373 · King James Version \(1769\) ·/)).toBeTruthy();
  });

    it("loads more results through the API's paging", async () => {
    search = "q=faith";
    serve((url) =>
      url.searchParams.get("offset") === "20"
        ? json(page([result({ chunk_id: "b", canonical_ref: "Hymn.2.1" })], { offset: 20 }))
        : json(page([result()], { next_offset: 20 })),
    );
    await renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "More results" }));
    expect(await screen.findByText("Hymn.2.1")).toBeTruthy();
    expect(screen.getAllByRole("listitem")).toHaveLength(2);
    expect(screen.queryByRole("button", { name: "More results" })).toBeNull();
  });

  it("says when nothing was found", async () => {
    search = "q=zzz";
    serve(() => json(page([])));
    await renderPage();
    expect(await screen.findByText(/No passages found/)).toBeTruthy();
  });

  it("explains a rate limit and lets the reader retry", async () => {
    search = "q=faith";
    let calls = 0;
    serve(() => (++calls === 1 ? json({ error: "too many" }, 429, { "retry-after": "7" }) : json(page([result()]))));
    await renderPage();
    expect((await screen.findByRole("alert")).textContent).toContain("Wait 7 seconds");
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText("Hymn.1.1")).toBeTruthy();
  });

  it("shows the API's reason when search is unavailable", async () => {
    search = "q=faith";
    serve(() => json({ error: "the embedding service did not answer in time" }, 503));
    await renderPage();
    expect((await screen.findByRole("alert")).textContent).toContain(
      "Search is unavailable right now (the embedding service did not answer in time)",
    );
  });

  it("notes that quoted phrases are searched by meaning for now", async () => {
    search = 'q="in the beginning"';
    serve(() => json(page([result()], { query: "in the beginning", requested_mode: "phrase" })));
    await renderPage();
    expect(await screen.findByText(/Exact-phrase search isn.t available yet/)).toBeTruthy();
  });
});
