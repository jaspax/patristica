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
    for (const f of ["b", "c", "d"]) await loadWork(`works/${f}.json`);
    await loadWork("works/a.json");
    expect(fetch).toHaveBeenCalledTimes(5);
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
