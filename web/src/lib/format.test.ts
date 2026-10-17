import { describe, expect, it } from "vitest";

import { formatAuthorDate, formatDate, formatDateLong, formatLifespan, formatYear } from "./format";

describe("dates", () => {
  it("formats years", () => {
    expect(formatYear(-500)).toBe("500 BC");
    expect(formatYear(397)).toBe("397");
  });

  it("formats table dates with confidence", () => {
    expect(formatDate({ date: 397, date_confidence: "established" })).toBe("397");
    expect(formatDate({ date: 397, date_confidence: "approximate" })).toBe("c. 397");
    expect(formatDate({ date: null, date_confidence: "uncertain" })).toBe("");
  });

  it("formats the long date with range", () => {
    expect(
      formatDateLong({ date: 475, date_range: [350, 600], date_confidence: "approximate" }),
    ).toBe("475 (350–600), approximate");
    expect(formatDateLong({ date: 314, date_range: [314, 314], date_confidence: "established" })).toBe(
      "314, established",
    );
    expect(formatDateLong({ date: null, date_range: null, date_confidence: "uncertain" })).toBe(
      "Undated",
    );
  });
});

describe("author dates", () => {
  it("writes the certainty as authors.csv does", () => {
    expect(formatAuthorDate({ low: 354, high: 354, confidence: "established" })).toBe("354");
    expect(formatAuthorDate({ low: 347, high: 347, confidence: "approximate" })).toBe("c. 347");
    expect(formatAuthorDate({ low: 350, high: 350, confidence: "uncertain" })).toBe("350?");
    expect(formatAuthorDate({ low: 340, high: 345, confidence: "established" })).toBe("340–345");
    expect(formatAuthorDate({ low: -20, high: -20, confidence: "approximate" })).toBe("c. 20 BC");
  });

  it("formats a lifespan for lists", () => {
    const d = (low: number, high = low, confidence: "established" | "approximate" | "uncertain" = "established") => ({
      low,
      high,
      confidence,
    });
    expect(formatLifespan({ birth: d(354), death: d(430), floruit: null })).toBe("354 – 430");
    expect(formatLifespan({ birth: d(347, 349, "approximate"), death: d(407), floruit: null })).toBe(
      "c. 347/349 – 407",
    );
    expect(formatLifespan({ birth: null, death: d(438, 438, "approximate"), floruit: null })).toBe("d. c. 438");
    expect(formatLifespan({ birth: null, death: null, floruit: d(431, 438) })).toBe("fl. 431–438");
    expect(formatLifespan({ birth: null, death: null, floruit: null })).toBe("");
  });
});
