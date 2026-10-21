import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

let loadWork: typeof import("./library").loadWork;

beforeEach(async () => {
  vi.resetModules();
  ({ loadWork } = await import("./library"));
});

afterEach(() => vi.unstubAllGlobals());

const body = (file: string) => ({ work_id: file, ref_prefix: "", chunks: [] });

describe("loadWork", () => {
  it("keeps the last few work files, so a version switch doesn't fetch twice", async () => {
    const fetch = vi.fn(async (url: string) => new Response(JSON.stringify(body(url))));
    vi.stubGlobal("fetch", fetch);
    await loadWork("works/a.json");
    await loadWork("works/a.json");
    expect(fetch).toHaveBeenCalledTimes(1);
    for (const f of ["b", "c", "d", "e", "f"]) await loadWork(`works/${f}.json`);
    await loadWork("works/a.json");
    expect(fetch).toHaveBeenCalledTimes(7);
  });

  it("retries a failed load", async () => {
    const fetch = vi
      .fn()
      .mockResolvedValueOnce(new Response("", { status: 503, statusText: "Unavailable" }))
      .mockResolvedValueOnce(new Response(JSON.stringify(body("a"))));
    vi.stubGlobal("fetch", fetch);
    await expect(loadWork("works/a.json")).rejects.toThrow(/503/);
    expect((await loadWork("works/a.json")).work_id).toBe("a");
  });
});

describe("alignments", () => {
  it("maps a version group to its file", async () => {
    const { alignmentPath, hasAlignment } = await import("./library");
    expect(alignmentPath("book:gen")).toBe("alignments/book/gen.json");
    expect(alignmentPath("ogpg/vol-032/epistulae")).toBe("alignments/ogpg/vol-032/epistulae.json");
    const index = { version: "v", sources: {}, works: [], alignments: ["book:gen"] };
    expect(hasAlignment(index, "book:gen")).toBe(true);
    expect(hasAlignment(index, "book:ex")).toBe(false);
    expect(hasAlignment(index, null)).toBe(false);
    // A library published before alignments were exported has no list.
    expect(hasAlignment({ ...index, alignments: undefined }, "book:gen")).toBe(false);
  });

  it("loads an alignment once and retries a failed load", async () => {
    const { loadAlignment } = await import("./library");
    const file = { group: "g", pivot: "a", groups: 0, members: {} };
    const fetch = vi
      .fn()
      .mockResolvedValueOnce(new Response("", { status: 404, statusText: "Not Found" }))
      .mockImplementation(async () => new Response(JSON.stringify(file)));
    vi.stubGlobal("fetch", fetch);
    await expect(loadAlignment("g")).rejects.toThrow(/404/);
    expect((await loadAlignment("g")).group).toBe("g");
    await loadAlignment("g");
    expect(fetch).toHaveBeenCalledTimes(2);
    expect(fetch.mock.calls[1][0]).toMatch(/alignments\/g\.json$/);
  });
});
