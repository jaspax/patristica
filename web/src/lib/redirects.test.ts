import { describe, expect, it } from "vitest";

import nextConfig from "../../next.config";
import { legacyWorkRedirects, SPLIT_OGPG_VOLUMES } from "./redirects";

describe("renamed work ids", () => {
  it("builds permanent reader redirects that keep the rest of the path", () => {
    expect(legacyWorkRedirects()).toContainEqual({
      source: "/works/liturgical/coptic-scriptorium/:rest+",
      destination: "/works/patristic/coptic-scriptorium/:rest+",
      permanent: true,
    });
  });

  it("matches only whole path segments under the old prefix", () => {
    for (const { source } of legacyWorkRedirects().filter((r) => r.source.includes(":rest"))) {
      expect(source).toMatch(/^\/works\/[^:]+\/:rest\+$/);
    }
  });

  it("is wired into next.config", async () => {
    expect(nextConfig.redirects).toBeDefined();
    const redirects = await nextConfig.redirects!();
    expect(redirects).toEqual(expect.arrayContaining(legacyWorkRedirects()));
  });
});

describe("split Patrologia Graeca volumes", () => {
  it("sends the old volume URL to the index filtered to the volume's works", () => {
    expect(legacyWorkRedirects()).toContainEqual({
      source: "/works/ogpg/vol-045",
      destination: "/?q=ogpg/vol-045/",
      permanent: true,
    });
  });

  it("redirects only the exact volume id, not its new works", () => {
    for (const vol of SPLIT_OGPG_VOLUMES) {
      expect(vol).toMatch(/^vol-\d{3}(-pt\d|-\d{3})?$/);
    }
    const sources = legacyWorkRedirects().map((r) => r.source);
    expect(sources.filter((s) => s.startsWith("/works/ogpg/")).every((s) => !s.includes(":"))).toBe(true);
  });
});
