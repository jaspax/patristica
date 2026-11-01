import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

// fonts.ts itself only runs inside Next's font loader, so these tests read
// the sources: the :lang() stacks in globals.css and the font files fonts.ts
// points at.
const dir = __dirname;
const css = readFileSync(join(dir, "globals.css"), "utf8");
const fontsTs = readFileSync(join(dir, "fonts.ts"), "utf8");

function langStack(lang: string): string[] {
  const rule = new RegExp(`:lang\\(${lang}\\)\\s*\\{\\s*font-family:\\s*([^;]+);`).exec(css);
  if (!rule) throw new Error(`no :lang(${lang}) font-family rule in globals.css`);
  return rule[1].split(",").map((s) => s.trim());
}

describe("Church Slavonic fonts (#371)", () => {
  it("backs Monomakh with the Slavonic fallback, then the body font", () => {
    expect(langStack("cu")).toEqual([
      "var(--font-slavonic)",
      "var(--font-slavonic-fallback)",
      "var(--font-body)",
    ]);
  });

  it("self-hosts both fonts as whole files, not Google's unicode-range slices", () => {
    const googleImports = /import \{([^}]*)\} from "next\/font\/google"/.exec(fontsTs)?.[1] ?? "";
    expect(googleImports).not.toContain("Monomakh");
    for (const variable of ["--font-slavonic", "--font-slavonic-fallback"]) {
      expect(fontsTs).toContain(`variable: "${variable}"`);
    }
    const files = [...fontsTs.matchAll(/src: "\.\/(fonts\/[^"]+\.woff2)"/g)].map((m) => m[1]);
    expect(files).toEqual([
      "fonts/Monomakh-Regular.woff2",
      "fonts/NotoSerif-Slavonic.woff2",
      "fonts/NotoSerif-Irish.woff2",
    ]);
    for (const file of files) {
      const bytes = readFileSync(join(dir, file));
      expect(bytes.subarray(0, 4).toString("latin1")).toBe("wOF2");
    }
  });

  it("ships the OFL licence next to each font", () => {
    expect(existsSync(join(dir, "fonts/Monomakh-OFL.txt"))).toBe(true);
    expect(existsSync(join(dir, "fonts/NotoSerif-OFL.txt"))).toBe(true);
  });
});

describe("Arabic font (#478)", () => {
  it("uses Noto Naskh Arabic, then the body font", () => {
    expect(langStack("ar")).toEqual(["var(--font-arabic)", "var(--font-body)"]);
    const googleImports = /import \{([^}]*)\} from "next\/font\/google"/.exec(fontsTs)?.[1] ?? "";
    expect(googleImports).toContain("Noto_Naskh_Arabic");
    expect(fontsTs).toContain('variable: "--font-arabic"');
  });
});

describe("Old Georgian font (#512)", () => {
  it("uses Noto Serif Georgian, then the body font", () => {
    expect(langStack("oge")).toEqual(["var(--font-georgian)", "var(--font-body)"]);
    const googleImports = /import \{([^}]*)\} from "next\/font\/google"/.exec(fontsTs)?.[1] ?? "";
    expect(googleImports).toContain("Noto_Serif_Georgian");
    expect(fontsTs).toContain('variable: "--font-georgian"');
  });
});

describe("Old Irish fonts (#544)", () => {
  it("keeps Noto Serif first, backed by the Irish fallback before the other script fonts", () => {
    expect(langStack("sga")).toEqual(["var(--font-serif)", "var(--font-irish-fallback)", "var(--font-body)"]);
    expect(fontsTs).toContain('variable: "--font-irish-fallback"');
    const bytes = readFileSync(join(dir, "fonts/NotoSerif-Irish.woff2"));
    expect(bytes.subarray(0, 4).toString("latin1")).toBe("wOF2");
  });
});
