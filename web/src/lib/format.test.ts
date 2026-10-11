import { describe, expect, it } from "vitest";

import { formatDate, formatDateLong, formatYear } from "./format";

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
