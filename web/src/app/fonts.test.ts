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
  const rule = new RegExp(`:lang\\(${lang}\\)[^{]*\\{\\s*font-family:\\s*([^;]+);`).exec(css);
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
      "fonts/Jigmo-Chinese.woff2",
      "fonts/Monomakh-Regular.woff2",
      "fonts/NotoSerif-Slavonic.woff2",
      "fonts/NotoSerif-Medieval.woff2",
      "fonts/Segotia-Regular.woff2",
      "fonts/NotoSansRunic-Runes.woff2",
      "fonts/BabelStoneEnglisc.woff2",
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

describe("Literary Chinese fonts (#649)", () => {
  it("uses Noto Serif TC, then the Jigmo subset, then the body font", () => {
    expect(langStack("lzh")).toEqual([
      "var(--font-chinese)",
      "var(--font-chinese-fallback)",
      "var(--font-body)",
    ]);
    const googleImports = /import \{([^}]*)\} from "next\/font\/google"/.exec(fontsTs)?.[1] ?? "";
    expect(googleImports).toContain("Noto_Serif_TC");
    expect(fontsTs).toMatch(/Noto_Serif_TC\(\{[^}]*variable: "--font-chinese",\s*preload: false/);
  });

  it("self-hosts the Jigmo subset with its CC0 licence and the list of its characters", () => {
    expect(fontsTs).toMatch(
      /src: "\.\/fonts\/Jigmo-Chinese\.woff2",\s*weight: "400",\s*variable: "--font-chinese-fallback",\s*preload: false,\s*adjustFontFallback: false/,
    );
    expect(readFileSync(join(dir, "fonts/Jigmo-LICENSE.txt"), "utf8")).toContain("CC0 1.0 Universal");
    const listed = readFileSync(join(dir, "fonts/Jigmo-Chinese.txt"), "utf8");
    // The supplementary-plane variants of the Taishō text and zh.wikisource's Ext-A characters.
    for (const cp of ["U+2DA1D", "U+2E2B5", "U+4ADF"]) expect(listed).toContain(cp);
  });

  it("keeps Chinese in the body stack, so text without a lang attribute still renders", () => {
    const body = /--font-body:([^;]+);/.exec(css)?.[1] ?? "";
    expect(body).toContain("var(--font-chinese), var(--font-chinese-fallback)");
  });
});

describe("Medieval Latin-script fonts (#544, #564)", () => {
  it.each(["sga", "ang", "goh", "osx"])(
    "keeps Noto Serif first for :lang(%s), backed by the medieval fallback and the runes before the other script fonts",
    (lang) => {
      expect(langStack(lang)).toEqual([
        "var(--font-serif)",
        "var(--font-medieval-fallback)",
        "var(--font-runic)",
        "var(--font-body)",
      ]);
    },
  );

  it("self-hosts the runes, loaded on demand, with no Arial fallback in the variable", () => {
    expect(fontsTs).toMatch(
      /src: "\.\/fonts\/NotoSansRunic-Runes\.woff2",\s*weight: "400",\s*variable: "--font-runic",\s*preload: false,\s*adjustFontFallback: false/,
    );
    expect(existsSync(join(dir, "fonts/NotoSansRunic-OFL.txt"))).toBe(true);
  });

  it("self-hosts the fallback", () => {
    expect(fontsTs).toContain('variable: "--font-medieval-fallback"');
    const bytes = readFileSync(join(dir, "fonts/NotoSerif-Medieval.woff2"));
    expect(bytes.subarray(0, 4).toString("latin1")).toBe("wOF2");
  });
});

describe("Faces for the Old Irish and Old English word tiles (#544, #564)", () => {
  const landingCss = readFileSync(join(dir, "../components/Landing.module.css"), "utf8");

  it("self-hosts Segotia and BabelStone Englisc with their licences, not preloaded", () => {
    expect(fontsTs).toMatch(/src: "\.\/fonts\/Segotia-Regular\.woff2",\s*weight: "400",\s*variable: "--font-insular",\s*preload: false/);
    expect(existsSync(join(dir, "fonts/Segotia-OFL.txt"))).toBe(true);
    expect(fontsTs).toMatch(/src: "\.\/fonts\/BabelStoneEnglisc\.woff2",\s*weight: "400",\s*variable: "--font-englisc",\s*preload: false/);
    expect(existsSync(join(dir, "fonts/BabelStoneEnglisc-OFL.txt"))).toBe(true);
  });

  it("are used by the landing tiles' classes only, never by a :lang() rule", () => {
    expect(landingCss).toMatch(/\.insular \{\s*font-family: var\(--font-insular\), var\(--font-body\);/);
    expect(landingCss).toMatch(/\.englisc \{\s*font-family: var\(--font-englisc\), var\(--font-body\);/);
    expect(css).not.toContain("--font-insular");
    expect(css).not.toContain("--font-englisc");
  });

  it("set Old Saxon and Old High German in UnifrakturMaguntia, by class only, not preloaded", () => {
    expect(fontsTs).toMatch(/UnifrakturMaguntia\(\{\s*subsets: \["latin"\],\s*weight: "400",\s*variable: "--font-fraktur",\s*preload: false/);
    expect(landingCss).toMatch(/\.fraktur \{\s*font-family: var\(--font-fraktur\), var\(--font-body\);/);
    expect(css).not.toContain("--font-fraktur");
  });
});
