import { describe, expect, it } from "vitest";

import nextConfig from "../../next.config";
import { legacyWorkRedirects } from "./redirects";

describe("renamed work ids", () => {
  it("builds permanent reader redirects that keep the rest of the path", () => {
    expect(legacyWorkRedirects()).toContainEqual({
      source: "/works/liturgical/coptic-scriptorium/:rest+",
      destination: "/works/patristic/coptic-scriptorium/:rest+",
      permanent: true,
    });
  });

  it("matches only whole path segments under the old prefix", () => {
    for (const { source } of legacyWorkRedirects()) {
      expect(source).toMatch(/^\/works\/[^:]+\/:rest\+$/);
    }
  });

  it("is wired into next.config", async () => {
    expect(nextConfig.redirects).toBeDefined();
    const redirects = await nextConfig.redirects!();
    expect(redirects).toEqual(expect.arrayContaining(legacyWorkRedirects()));
  });
});
