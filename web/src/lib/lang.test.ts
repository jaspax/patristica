import { describe, expect, it } from "vitest";

import { LANGUAGES, languageInfo } from "./lang";

describe("languageInfo", () => {
  it("maps ISO 639-3 codes to BCP 47 lang tags", () => {
    expect(languageInfo("lat").lang).toBe("la");
    expect(languageInfo("eng").lang).toBe("en");
    expect(languageInfo("hye").lang).toBe("hy");
    expect(languageInfo("grc").lang).toBe("grc");
  });

  it("marks Hebrew and Syriac as right-to-left", () => {
    const rtl = Object.entries(LANGUAGES)
      .filter(([, info]) => info.dir === "rtl")
      .map(([code]) => code)
      .sort();
    expect(rtl).toEqual(["hbo", "syc"]);
  });

  it("passes unknown codes through", () => {
    expect(languageInfo("xyz")).toEqual({ lang: "xyz", name: "xyz", dir: "ltr" });
  });
});
