import { describe, expect, it } from "vitest";

import nextConfig from "../../next.config";
import { currentSourceId, currentWorkId, legacyWorkRedirects, SPLIT_OGPG_VOLUMES } from "./redirects";

describe("renamed work ids", () => {
  it("drops the genre prefix that ids had before #102", () => {
    expect(legacyWorkRedirects()).toContainEqual({
      source: "/works/scripture/:rest+",
      destination: "/works/:rest+",
      permanent: true,
    });
    expect(currentWorkId("scripture/kjv/gen")).toBe("kjv/gen");
    expect(currentWorkId("liturgical/cursus/Bat")).toBe("cursus/Bat");
  });

  it("sends both old Coptic Scriptorium prefixes (#52, #102) to the current id in one hop", () => {
    expect(currentWorkId("liturgical/coptic-scriptorium/AP")).toBe("coptic-scriptorium/AP");
    expect(currentWorkId("patristic/coptic-scriptorium/AP")).toBe("coptic-scriptorium/AP");
    const sources = legacyWorkRedirects().map((r) => r.source);
    expect(sources).not.toContain("/works/liturgical/coptic-scriptorium/:rest+");
  });

  it("renames council and Patrologia Latina work ids to their source ids", () => {
    expect(legacyWorkRedirects()).toContainEqual({
      source: "/works/councils/:rest+",
      destination: "/works/ecumenical/:rest+",
      permanent: true,
    });
    expect(currentWorkId("councils/nicaea1")).toBe("ecumenical/nicaea1");
    expect(currentWorkId("oglt_pl/augustinus/pl32_5_s")).toBe("oglt-pl/augustinus/pl32_5_s");
  });

  it("leaves current ids alone", () => {
    for (const id of ["kjv/gen", "ogpg/vol-045/ad-graecos", "first1k/tlg2042/tlg001/1st1K-grc1"]) {
      expect(currentWorkId(id)).toBe(id);
    }
    expect(currentWorkId("scripturex/a")).toBe("scripturex/a");
  });

  it("maps old source ids to the bare collection slug (#70)", () => {
    expect(currentSourceId("scripture/oshb")).toBe("oshb");
    expect(currentSourceId("patristic/oglt-pl")).toBe("oglt-pl");
    expect(currentSourceId("councils/ecumenical")).toBe("ecumenical");
    expect(currentSourceId("ogpg")).toBe("ogpg");
    expect(currentSourceId("")).toBe("");
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
