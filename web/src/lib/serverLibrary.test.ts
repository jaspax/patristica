import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

let serverLibrary: typeof import("./serverLibrary").serverLibrary;
let REFRESH_MS: number;

beforeEach(async () => {
  vi.resetModules();
  vi.stubEnv("NEXT_PUBLIC_LIBRARY_URL", "https://cdn.example/lib");
  ({ serverLibrary, REFRESH_MS } = await import("./serverLibrary"));
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});

const files: Record<string, unknown> = {
  "https://cdn.example/lib/index.json": { version: "v", sources: {}, works: [] },
  "https://cdn.example/lib/authors.json": { authors: [{ id: "a", name: "A" }] },
};
const ok = vi.fn(async (url: string) => new Response(JSON.stringify(files[url])));

describe("serverLibrary", () => {
  it("loads the index and authors once per refresh period", async () => {
    vi.stubGlobal("fetch", ok);
    ok.mockClear();
    const library = await serverLibrary(0);
    expect(library.authors.get("a")?.name).toBe("A");
    await serverLibrary(REFRESH_MS);
    expect(ok).toHaveBeenCalledTimes(2);
    await serverLibrary(REFRESH_MS + 1);
    expect(ok).toHaveBeenCalledTimes(4);
  });

  it("retries a failed load", async () => {
    const fetch = vi
      .fn()
      .mockResolvedValueOnce(new Response("", { status: 503, statusText: "Unavailable" }))
      .mockImplementation(ok);
    vi.stubGlobal("fetch", fetch);
    await expect(serverLibrary(0)).rejects.toThrow("503 Unavailable");
    await expect(serverLibrary(1)).resolves.toBeTruthy();
  });
});
