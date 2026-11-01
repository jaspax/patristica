import { describe, expect, it } from "vitest";

import { LANGUAGES, languageInfo } from "./lang";

describe("languageInfo", () => {
  it("maps ISO 639-3 codes to BCP 47 lang tags", () => {
    expect(languageInfo("lat").lang).toBe("la");
    expect(languageInfo("eng").lang).toBe("en");
    expect(languageInfo("hye").lang).toBe("hy");
    expect(languageInfo("grc").lang).toBe("grc");
    expect(languageInfo("chu")).toEqual({ lang: "cu", name: "Church Slavonic", dir: "ltr" });
  });

  it("maps Old Georgian to oge (not modern Georgian ka), left-to-right", () => {
    expect(languageInfo("oge")).toEqual({ lang: "oge", name: "Old Georgian", dir: "ltr" });
  });

  it("maps Old Irish to sga (not modern Irish ga), left-to-right", () => {
    expect(languageInfo("sga")).toEqual({ lang: "sga", name: "Old Irish", dir: "ltr" });
  });

  it("maps Arabic to ar, right-to-left", () => {
    expect(languageInfo("arb")).toEqual({ lang: "ar", name: "Arabic", dir: "rtl" });
  });

  it("marks Hebrew, Syriac and Arabic as right-to-left", () => {
    const rtl = Object.entries(LANGUAGES)
      .filter(([, info]) => info.dir === "rtl")
      .map(([code]) => code)
      .sort();
    expect(rtl).toEqual(["arb", "hbo", "syc"]);
  });

  it("passes unknown codes through", () => {
    expect(languageInfo("xyz")).toEqual({ lang: "xyz", name: "xyz", dir: "ltr" });
  });
});
