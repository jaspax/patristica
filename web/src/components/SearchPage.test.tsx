import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { AuthorsFile, LibraryIndex } from "@/lib/library";
import type { SearchResponse, SearchResult } from "@/lib/search";
import { person, workRow } from "@/lib/testFixtures";

const push = vi.fn();
let search = "";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push }),
  usePathname: () => "/",
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
    text_start: 0,
    matches: [],
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
    versions: [],
    ...overrides,
  };
}

function page(results: SearchResult[], overrides: Partial<SearchResponse> = {}): SearchResponse {
  return {
    query: "faith",
    mode: "vector",
    phrases: [],
    text: "faith",
    total: null,
    limit: 20,
    next_cursor: null,
    results,
    ...overrides,
  };
}

/** Serve the library files, and `api` for /api/search requests (by cursor). */
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
    expect(push).toHaveBeenCalledWith("/?q=faith", { scroll: false });

    fireEvent.click(screen.getByRole("button", { name: "Filters" }));
    fireEvent.click(await screen.findByRole("button", { name: "Language All" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "Syriac" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "English" }));
    fireEvent.click(screen.getByRole("button", { name: "Done" }));
    // One push for the query, one for the whole language selection.
    expect(push).toHaveBeenCalledTimes(2);
    expect(push).toHaveBeenLastCalledWith("/?language=syc&language=eng", { scroll: false });
  });

  it("shows the Search button as busy while the first page loads", async () => {
    search = "q=faith";
    let respond: (r: Response) => void = () => {};
    const pending = new Promise<Response>((resolve) => (respond = resolve));
    serve(() => pending as unknown as Response);
    await renderPage();
    const button = screen.getByRole("button", { name: "Search" });
    await waitFor(() => expect(button.getAttribute("aria-busy")).toBe("true"));
    respond(json(page([result()])));
    await waitFor(() => expect(button.getAttribute("aria-busy")).toBe("false"));
  });

  it("folds the filters away below the search bar until a link sets one", async () => {
    serve(() => json(page([])));
    await renderPage();
    const toggle = screen.getByRole("button", { name: "Filters" });
    const panel = document.getElementById(toggle.getAttribute("aria-controls")!)!;
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    expect(panel.hidden).toBe(true);
    expect(screen.queryByRole("button", { name: "Clear filters" })).toBeNull();
    fireEvent.click(toggle);
    expect(toggle.getAttribute("aria-expanded")).toBe("true");
    expect(panel.hidden).toBe(false);
    cleanup();

    search = "q=faith&language=syc&from=300&to=400";
    serve(() => json(page([])));
    await renderPage();
    expect(screen.getByRole("button", { name: "Filters (2)" }).getAttribute("aria-expanded")).toBe("true");
  });

  it("clears the filters from beside the toggle, even with the panel closed", async () => {
    search = "q=faith&language=syc";
    serve(() => json(page([])));
    await renderPage();
    fireEvent.click(screen.getByRole("button", { name: "Filters (1)" }));
    fireEvent.click(screen.getByRole("button", { name: "Clear filters" }));
    expect(push).toHaveBeenLastCalledWith("/?q=faith", { scroll: false });
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
    const text = within(item).getByText("ܗܝܡܢܘܬܐ ܕܝܠܢ ܫܪܝܪܬܐ").closest("p")!;
    expect(text.getAttribute("lang")).toBe("syc");
    expect(text.getAttribute("dir")).toBe("rtl");
    expect(within(item).getByText("Machine translation (English)")).toBeTruthy();
    expect(within(item).getByText("Our faith is true.").closest("p")!.getAttribute("lang")).toBe("en");
    expect(within(item).getByText(/350–373 · Patristic Text Archive, PTA/)).toBeTruthy();
    expect(within(item).getByRole("link", { name: "CC BY-SA 4.0" })).toBeTruthy();
    expect(item.textContent).not.toContain("pta/hymns");
  });

  it("shows the units before and after a result, dimmed, in its script", async () => {
    search = "q=void";
    serve(() =>
      json(
        page([
          result({
            context: {
              before: { chunk_id: "pta/hymns#Hymn.1.0", canonical_ref: "Hymn.1.0", text: "ܩܕܡ" },
              after: { chunk_id: "pta/hymns#Hymn.1.2", canonical_ref: "Hymn.1.2", text: "ܒܬܪ" },
            },
            translation: { language: "eng", text: "Our faith is true.", model: "gpt-6.1-sol", machine: true, before: "Before.", after: null },
          }),
        ]),
      ),
    );
    await renderPage();
    const item = (await screen.findAllByRole("listitem"))[0];
    const before = within(item).getByText("ܩܕܡ");
    const text = before.closest("p")!;
    expect(text.getAttribute("lang")).toBe("syc");
    expect(text.textContent).toBe("ܩܕܡ ܗܝܡܢܘܬܐ ܕܝܠܢ ܫܪܝܪܬܐ ܒܬܪ");
    expect(before.className).toMatch(/context/);
    expect(within(item).getByText("ܗܝܡܢܘܬܐ ܕܝܠܢ ܫܪܝܪܬܐ").className).toMatch(/hit/);
    // The translation carries the same context, where it has it.
    expect(within(item).getByText("Our faith is true.").closest("p")!.textContent).toBe("Before. Our faith is true.");
  });

  it("names and links a linked English version instead of a machine translation", async () => {
    search = "q=void";
    serve(() =>
      json(
        page([
          result({
            chunk_id: "lxx-rahlfs/gen#Gen.1.2",
            work_id: "lxx-rahlfs/gen",
            canonical_ref: "Gen.1.2",
            language: "grc",
            text: "ἡ δὲ γῆ ἦν ἀόρατος",
            translation: {
              language: "eng",
              text: "And the earth was without form, and void.",
              machine: false,
              model: null,
              before: "In the beginning God created the heaven and the earth.",
              after: null,
              work_id: "kjv/gen",
              canonical_ref: "Gen.1.2",
              source_label: "King James Version",
              edition: "King James Version (1769)",
            },
          }),
        ]),
      ),
    );
    await renderPage();
    const item = (await screen.findAllByRole("listitem"))[0];
    expect(within(item).queryByText("Machine translation (English)")).toBeNull();
    const link = within(item).getByRole("link", { name: "King James Version" });
    expect(link.getAttribute("href")).toBe("/works/kjv/gen#Gen.1.2");
    expect(within(item).getByText(/^English:/).textContent).toBe("English: King James Version Gen.1.2");
  });

  it("labels a machine-translated work of the library as machine translation, linked (#422)", async () => {
    search = "q=oratio";
    serve(() =>
      json(
        page([
          result({
            translation: {
              language: "eng",
              text: "Our faith is true.",
              machine: true,
              model: "claude-opus-5-5",
              work_id: "mt-eng/pta/or",
              canonical_ref: "Or.1",
              source_label: "Patristica machine translations",
            },
          }),
        ]),
      ),
    );
    await renderPage();
    const item = (await screen.findAllByRole("listitem"))[0];
    expect(within(item).getByText(/^Machine translation \(English\):/)).toBeTruthy();
    const link = within(item).getByRole("link", { name: "Patristica machine translations" });
    expect(link.getAttribute("href")).toBe("/works/mt-eng/pta/or#Or.1");
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

  it("lists the other versions of a folded passage, each linking to it", async () => {
    search = "q=shepherd";
    const version = (chunk_id: string, language: string, source_label: string, canonical_ref = "Ps.23.1") => ({
      chunk_id,
      work_id: chunk_id.split("#")[0],
      canonical_ref,
      language,
      source_label,
      edition: `${source_label} (edition)`,
      score: 0.8,
    });
    serve(() =>
      json(
        page([
          result({
            chunk_id: "kjv/ps#Ps.23.1",
            work_id: "kjv/ps",
            canonical_ref: "Ps.23.1",
            language: "eng",
            translation: null,
            versions: [
              version("oshb/ps#Ps.23.1", "hbo", "Open Scriptures Hebrew Bible"),
              version("asv/ps#Ps.23.1", "eng", "American Standard Version"),
              version("zohrab/ps#Ps.22.2", "hye", "Zohrab Bible", "Ps.22.2"),
              version("web/ps#Ps.23.1", "eng", "World English Bible"),
            ],
          }),
          result(),
        ]),
      ),
    );
    await renderPage();
    const versions = await screen.findByRole("list", { name: "Also in:" });
    const [folded, single] = [...document.querySelectorAll<HTMLElement>("ol > li")];
    expect(folded.contains(versions)).toBe(true);
    // One item per language, in the order of each language's best version.
    expect(within(versions).getAllByRole("listitem").map((li) => li.textContent)).toEqual([
      "Hebrew: Open Scriptures Hebrew Bible",
      "English: American Standard Version, World English Bible",
      "Armenian: Zohrab Bible Ps.22.2",
    ]);
    expect(within(versions).getByRole("link", { name: "World English Bible" }).getAttribute("href")).toBe(
      "/works/web/ps#Ps.23.1",
    );
    // A version numbered differently links to its own ref.
    expect(within(versions).getByRole("link", { name: "Zohrab Bible Ps.22.2" }).getAttribute("href")).toBe(
      "/works/zohrab/ps#Ps.22.2",
    );
    expect(folded.textContent).not.toMatch(/oshb|zohrab\/|asv\//);
    // A passage with no other versions has no list.
    expect(within(single).queryByText("Also in:")).toBeNull();
  });

    it("loads more results through the API's paging", async () => {
    search = "q=faith";
    serve((url) =>
      url.searchParams.get("cursor") === "page2"
        ? json(page([result({ chunk_id: "b", canonical_ref: "Hymn.2.1" })]))
        : json(page([result()], { next_cursor: "page2" })),
    );
    await renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "More results" }));
    expect(screen.getByRole("status").textContent).toBe("Searching…");
    expect(await screen.findByText("Hymn.2.1")).toBeTruthy();
    expect(screen.getAllByRole("listitem")).toHaveLength(2);
    expect(screen.queryByRole("button", { name: "More results" })).toBeNull();
    await waitFor(() => expect(screen.getByRole("status").textContent).toBe("2 passages shown."));
  });

  it("says when nothing was found", async () => {
    search = "q=zzz";
    serve(() => json(page([])));
    await renderPage();
    expect(await screen.findByText(/No passages found/)).toBeTruthy();
    await waitFor(() => expect(screen.getByRole("status").textContent).toBe("No passages found."));
  });

  it("announces how many passages are shown", async () => {
    search = "q=faith";
    serve(() => json(page([result()], { next_cursor: "page2" })));
    await renderPage();
    await screen.findByText("Hymn.1.1");
    await waitFor(() => expect(screen.getByRole("status").textContent).toBe("1 passage shown, more available."));
  });

  it("explains a reversed date range without sending the search", async () => {
    search = "q=faith&from=500&to=300";
    const fetch = serve(() => json(page([result()])));
    await renderPage();
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("The start year is after the end year");
    expect(within(alert).queryByRole("button", { name: "Try again" })).toBeNull();
    expect(fetch.mock.calls.some(([u]) => String(u).startsWith("/api/"))).toBe(false);
  });

  it("shows the API's reason for a rejected search", async () => {
    search = "q=faith";
    serve(() => json({ error: "date_from is after date_to" }, 422));
    await renderPage();
    expect((await screen.findByRole("alert")).textContent).toContain("date_from is after date_to");
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

  it("labels semantic search", async () => {
    search = "q=faith";
    serve(() => json(page([result()])));
    await renderPage();
    expect((await screen.findByText("Semantic", { selector: "section strong" })).parentElement?.textContent).toBe(
      "Semantic · passages closest in meaning",
    );
  });

  /** A keyword-mode page for the phrase "in principio" with one Latin result. */
  function phrasePage(overrides: Partial<SearchResponse> = {}) {
    const text = "In principio erat Verbum, et Verbum erat apud Deum.";
    return page(
      [
        result({
          language: "lat",
          text,
          translation: null,
          score: null,
          matched: "phrase",
          matches: [[0, 12]],
        }),
      ],
      { mode: "keyword", phrases: ["in principio"], text: "", total: 386, next_cursor: "page2", ...overrides },
    );
  }

  it("labels exact-phrase search and highlights the matches", async () => {
    search = 'q="in principio"';
    const fetch = serve(() => json(phrasePage()));
    await renderPage();
    const label = await screen.findByText("Exact phrase", { selector: "section strong" });
    expect(label.parentElement?.textContent).toBe(
      "Exact phrase · passages containing in principio, Scripture first, then the earliest · 386 found",
    );
    const mark = document.querySelector("li mark");
    expect(mark?.textContent).toBe("In principio");
    expect(mark?.parentElement?.textContent).toBe("In principio erat Verbum, et Verbum erat apud Deum.");
    // The quotes reach the API as typed.
    expect(fetch.mock.calls.map(([u]) => String(u))).toContain("/api/search?q=%22in+principio%22&limit=20");
    await waitFor(() =>
      expect(screen.getByRole("status").textContent).toBe("1 of 386 passages shown, more available."),
    );
  });

  it("says when free text ranks the phrase matches", async () => {
    search = 'q="in principio" creation';
    serve(() => json(phrasePage({ text: "creation" })));
    await renderPage();
    expect((await screen.findByText("Exact phrase", { selector: "section strong" })).parentElement?.textContent).toContain(
      "closest in meaning to creation first",
    );
  });

  it("marks a passage shown from a later match", async () => {
    search = 'q="in principio"';
    serve(() => json(phrasePage({ results: [{ ...phrasePage().results[0], text_start: 1800 }] })));
    await renderPage();
    expect((await screen.findByText("In principio")).parentElement?.textContent).toMatch(/^…In principio/);
  });

  it("offers a semantic search when no passage contains the phrase", async () => {
    search = "q=%22in+principio%22+%C2%ABverbum%C2%BB";
    serve(() => json(phrasePage({ results: [], total: null, next_cursor: null, phrases: ["in principio", "verbum"] })));
    await renderPage();
    expect(await screen.findByText(/No passages contain these phrases/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Search by meaning instead" }));
    expect(push).toHaveBeenCalledWith("/?q=in+principio+verbum", { scroll: false });
  });

  it("keeps quotes in the URL as typed", async () => {
    serve(() => json(page([])));
    await renderPage();
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "«ἐν ἀρχῇ» logos" } });
    fireEvent.submit(screen.getByRole("search"));
    expect(push).toHaveBeenCalledWith(`/?q=${encodeURIComponent("«ἐν ἀρχῇ»").replace(/%20/g, "+")}+logos`, {
      scroll: false,
    });
  });

  it("explains the search syntax", async () => {
    serve(() => json(page([])));
    await renderPage();
    // The hint describes the search box without becoming part of its name.
    const box = screen.getByRole("searchbox", { name: "Search the texts" });
    expect(document.getElementById(box.getAttribute("aria-describedby") ?? "")?.textContent).toMatch(
      /^Put words in quotes for an exact phrase/,
    );
    fireEvent.click(screen.getByText("How search works"));
    expect(screen.getByText(/Accents,\s+breathings, vowel points and capitals/)).toBeTruthy();
  });
});
