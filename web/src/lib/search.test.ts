import { afterEach, describe, expect, it, vi } from "vitest";

import {
  DEFAULT_SEARCH,
  fetchSearch,
  formatRange,
  highlight,
  parseSearchState,
  resultHref,
  searchApiUrl,
  searchHref,
  SearchError,
  searchStateToParams,
  withoutQuotes,
} from "./search";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("search URL state", () => {
  it("round-trips through the URL query, omitting defaults", () => {
    const state = { ...DEFAULT_SEARCH, q: "grace", language: "syc", from: 300 };
    const params = searchStateToParams(state);
    expect(params.toString()).toBe("q=grace&language=syc&from=300");
    expect(parseSearchState(params)).toEqual(state);
  });

  it("ignores the library index's sort parameters", () => {
    expect(parseSearchState(new URLSearchParams("q=x&sort=title&dir=desc"))).toEqual({ ...DEFAULT_SEARCH, q: "x" });
  });

  it("builds shareable links", () => {
    expect(searchHref({ q: "light of Tabor", author: "anonymous" })).toBe("/?q=light+of+Tabor&author=anonymous");
    expect(searchHref({})).toBe("/");
  });
});

describe("searchApiUrl", () => {
  it("maps the state onto the API's parameters", () => {
    const url = searchApiUrl({ ...DEFAULT_SEARCH, q: " faith ", genre: "patristic", from: -100, to: 400 }, 20);
    expect(url).toBe("/api/search?q=faith&genre=patristic&date_from=-100&date_to=400&limit=20&offset=20");
  });
});

describe("resultHref", () => {
  it("links to the passage in the reader", () => {
    expect(resultHref({ work_id: "pta/ephrem hymns", canonical_ref: "Hymn.1.2.s3" })).toBe(
      "/works/pta/ephrem%20hymns#Hymn.1.2.s3",
    );
  });
});

describe("withoutQuotes", () => {
  it("drops every kind of quote mark", () => {
    expect(withoutQuotes('"in principio" «ἐν ἀρχῇ»  „Wort“ “light”')).toBe("in principio ἐν ἀρχῇ Wort light");
  });
});

describe("highlight", () => {
  const marked = (text: string, matches: [number, number][]) =>
    highlight(text, matches).map((s) => (s.match ? `[${s.text}]` : s.text)).join("");

  it("splits text at the API's offsets", () => {
    expect(marked("In principio erat Verbum", [[0, 12], [18, 24]])).toBe("[In principio] erat [Verbum]");
    expect(highlight("abc", [])).toEqual([{ text: "abc", match: false }]);
  });

  it("keeps combining marks with their letters in right-to-left text", () => {
    // Pointed Hebrew: the API's span covers the vowel points after the last letter.
    const text = "בְּרֵאשִׁית בָּרָא אֱלֹהִים";
    const end = "בְּרֵאשִׁית בָּרָא".length;
    expect(marked(text, [[0, end]])).toBe("[בְּרֵאשִׁית בָּרָא] אֱלֹהִים");
  });

  it("uses UTF-16 indices, so letters outside the BMP stay whole", () => {
    const text = "𐌹𐌽 𐌰𐌽𐌰𐍃𐍄𐍉𐌳𐌴𐌹𐌽";
    expect(marked(text, [[5, 25]])).toBe("𐌹𐌽 [𐌰𐌽𐌰𐍃𐍄𐍉𐌳𐌴𐌹𐌽]");
  });

  it("clamps bad offsets instead of losing text", () => {
    expect(marked("abcdef", [[4, 2], [3, 99]])).toBe("abcd[ef]");
    expect(marked("abc", [[-5, 1]])).toBe("[a]bc");
  });
});

describe("formatRange", () => {
  it("formats ranges, years and undated passages", () => {
    expect(formatRange([350, 373])).toBe("350–373");
    expect(formatRange([-900, -400])).toBe("900 BC–400 BC");
    expect(formatRange([397, 397])).toBe("397");
    expect(formatRange(null, 120)).toBe("120");
    expect(formatRange(null)).toBe("");
  });
});

function respond(status: number, body: unknown, headers: Record<string, string> = {}) {
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(body), { status, headers })));
}

describe("fetchSearch", () => {
  const state = { ...DEFAULT_SEARCH, q: "x" };

  it("returns the response", async () => {
    respond(200, { results: [], next_offset: null });
    await expect(fetchSearch(state)).resolves.toEqual({ results: [], next_offset: null });
  });

  it.each([
    [429, { error: "too many searches" }, { "retry-after": "12" }, "rate-limited", 12],
    [503, { error: "the embedding service did not answer in time" }, {}, "unavailable", null],
    [422, { detail: [] }, {}, "invalid", null],
    [500, "oops", {}, "failed", null],
  ])("turns HTTP %i into a SearchError", async (status, body, headers, kind, retryAfter) => {
    respond(status, body, headers);
    const err = await fetchSearch(state).catch((e: unknown) => e);
    expect(err).toBeInstanceOf(SearchError);
    expect((err as SearchError).kind).toBe(kind);
    expect((err as SearchError).retryAfter).toBe(retryAfter);
  });

  it("rejects a reversed date range without a request", async () => {
    const fetch = vi.fn();
    vi.stubGlobal("fetch", fetch);
    const err = await fetchSearch({ ...state, from: 500, to: 300 }).catch((e: unknown) => e);
    expect(err).toMatchObject({ kind: "invalid", message: expect.stringContaining("start year is after the end year") });
    expect(fetch).not.toHaveBeenCalled();
  });

  it("shows the API's reason for a 422, or a hint about the query and dates", async () => {
    respond(422, { error: "date_from is after date_to" });
    await expect(fetchSearch(state)).rejects.toMatchObject({ kind: "invalid", message: "date_from is after date_to" });
    respond(422, { detail: [] });
    await expect(fetchSearch(state)).rejects.toThrow(/date filters/);
  });

  it("keeps the API's message for 503", async () => {
    respond(503, { error: "search is not configured on this server" });
    await expect(fetchSearch(state)).rejects.toThrow("search is not configured on this server");
  });

  it("reports network failures and timeouts", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => Promise.reject(new TypeError("Failed to fetch"))));
    await expect(fetchSearch(state)).rejects.toMatchObject({ kind: "failed" });

    vi.stubGlobal(
      "fetch",
      vi.fn(
        (_url: string, init: RequestInit) =>
          new Promise((_resolve, reject) => init.signal?.addEventListener("abort", () => reject(new Error("aborted")))),
      ),
    );
    await expect(fetchSearch(state, 0, undefined, 5)).rejects.toMatchObject({ kind: "timeout" });
  });

  /** A response whose body never arrives, and errors when the request is aborted. */
  function stallBody() {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (_url: string, init: RequestInit) => {
        const body = new ReadableStream({
          start(controller) {
            init.signal?.addEventListener("abort", () =>
              controller.error(new DOMException("aborted", "AbortError")),
            );
          },
        });
        return new Response(body, { status: 200 });
      }),
    );
  }

  it("times out while the body is still arriving", async () => {
    stallBody();
    await expect(fetchSearch(state, 0, undefined, 5)).rejects.toMatchObject({ kind: "timeout" });
  });

  it("cancels the body read when the caller aborts", async () => {
    stallBody();
    const controller = new AbortController();
    const pending = fetchSearch(state, 0, controller.signal);
    await new Promise((r) => setTimeout(r, 0));
    controller.abort();
    const err = await pending.catch((e: unknown) => e);
    expect(err).not.toBeInstanceOf(SearchError);
  });

  it("passes the caller's abort through unchanged", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(
        (_url: string, init: RequestInit) =>
          new Promise((_resolve, reject) => init.signal?.addEventListener("abort", () => reject(new Error("aborted")))),
      ),
    );
    const controller = new AbortController();
    const pending = fetchSearch(state, 0, controller.signal);
    controller.abort();
    const err = await pending.catch((e: unknown) => e);
    expect(err).not.toBeInstanceOf(SearchError);
  });
});
