// Fonts for every script in the corpus, exposed as CSS variables.
// Only the body font is preloaded; the script fonts load on demand through
// their unicode-range when a page uses them (the self-hosted Slavonic fonts
// when a :lang(cu) text is shown). globals.css picks the font per
// language with :lang() rules (see lib/lang.ts for the lang values).
import localFont from "next/font/local";
import {
  Cinzel,
  Noto_Naskh_Arabic,
  Noto_Sans_Coptic,
  Noto_Sans_Gothic,
  Noto_Sans_Syriac,
  Noto_Serif,
  Noto_Serif_Armenian,
  Noto_Serif_Ethiopic,
  Noto_Serif_Hebrew,
} from "next/font/google";

const serif = Noto_Serif({
  subsets: ["latin", "latin-ext", "greek", "greek-ext"],
  variable: "--font-serif",
});

// Roman inscriptional capitals for the wordmark and the landing page's heading.
const display = Cinzel({
  subsets: ["latin"],
  weight: ["500", "600"],
  variable: "--font-display",
});

const hebrew = Noto_Serif_Hebrew({
  subsets: ["hebrew"],
  variable: "--font-hebrew",
  preload: false,
});

const syriac = Noto_Sans_Syriac({
  subsets: ["syriac"],
  variable: "--font-syriac",
  preload: false,
});

const coptic = Noto_Sans_Coptic({
  subsets: ["coptic"],
  weight: "400",
  variable: "--font-coptic",
  preload: false,
});

const ethiopic = Noto_Serif_Ethiopic({
  subsets: ["ethiopic"],
  variable: "--font-ethiopic",
  preload: false,
});

const armenian = Noto_Serif_Armenian({
  subsets: ["armenian"],
  variable: "--font-armenian",
  preload: false,
});

const gothic = Noto_Sans_Gothic({
  subsets: ["gothic"],
  weight: "400",
  variable: "--font-gothic",
  preload: false,
});

// Arabic (#83, #478). Google serves Noto Naskh Arabic sliced, but its
// "arabic" slice holds all of U+0600–06FF (letters, harakat, superscript alef
// U+0670, alef wasla U+0671, tatweel, Arabic punctuation) and the Presentation
// Forms, so a letter and its vowel marks always come from one file (cf. #371).
const arabic = Noto_Naskh_Arabic({
  subsets: ["arabic"],
  variable: "--font-arabic",
  preload: false,
});

// Church Slavonic (#330, #371): Monomakh is made for early Cyrillic
// manuscripts and covers every Old Church Slavonic letter the sources use
// (Cyrillic Extended-A superscript letters, Extended-B ꙇ ꙑ ꙙ ꙉ ꙁ ꙗ, the titla,
// the inverted breve, ⁖ ⁘ ⁛). Ponomar lacks ꙇ, ꙑ and ꙙ.
// It is self-hosted whole (web/scripts/slavonic-fonts.py): Google Fonts serves
// it sliced by unicode-range, with the Cyrillic letters and the superscript
// letters in different files, and Chromium draws a letter and its combining
// marks from one file, so a cluster like кⷰ҇ found no file with all three and
// rendered as tofu.
// adjustFontFallback is off, so no metric-adjusted Arial sits between these
// fonts in the stack and takes the clusters Monomakh can't draw.
const slavonic = localFont({
  src: "./fonts/Monomakh-Regular.woff2",
  weight: "400",
  variable: "--font-slavonic",
  preload: false,
  adjustFontFallback: false,
});

// The fallback for what Monomakh lacks (precomposed ӗ ӓ ӥ, the combining
// double macron, Extended-B U+A680–A697): Noto Serif cut to Cyrillic, its
// combining marks and punctuation, in one file, so a cluster Monomakh can't
// draw falls back whole instead of splitting across files.
const slavonicFallback = localFont({
  src: "./fonts/NotoSerif-Slavonic.woff2",
  weight: "400",
  variable: "--font-slavonic-fallback",
  preload: false,
  adjustFontFallback: false,
});

/** Class names that define all font CSS variables; put on <html>. */
export const fontVariables = [
  serif,
  display,
  hebrew,
  syriac,
  coptic,
  ethiopic,
  armenian,
  gothic,
  arabic,
  slavonic,
  slavonicFallback,
]
  .map((f) => f.variable)
  .join(" ");
