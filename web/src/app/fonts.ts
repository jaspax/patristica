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
  Noto_Serif_Georgian,
  Noto_Serif_Hebrew,
  Noto_Serif_TC,
  UnifrakturMaguntia,
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

// Old Georgian (#222, #512). Google serves Noto Serif Georgian's Georgian in
// one "georgian" slice (U+10A0–10FF, U+1C90–1CBF, U+2D00–2D2F): Mkhedruli with
// the archaic letters ჱ ჲ ჳ ჴ ჵ ჶ ჷ and ჻, Asomtavruli, Nuskhuri and Mtavruli
// are all in one file. Georgian has no combining marks, so no cluster can
// split across slices (cf. #371).
const georgian = Noto_Serif_Georgian({
  subsets: ["georgian"],
  variable: "--font-georgian",
  preload: false,
});

// Literary Chinese (#228, #649): Noto Serif TC, traditional characters as the
// sources print them. Google serves it in ~100 unicode-range slices, so a page
// fetches only the slices its characters fall in; none is preloaded. Han
// characters take no combining marks, so no cluster can split across slices
// (cf. #371).
const chinese = Noto_Serif_TC({
  weight: "variable",
  variable: "--font-chinese",
  preload: false,
});

// What Noto Serif TC lacks: the Taishō's supplementary-plane variants
// (𭨝 U+2DA1D, 𮊵 U+2E2B5, …), Ext-A characters (䫟) and the Japanese and
// simplified forms the sources keep (将 来 浄). Cut from Jigmo (CC0 1.0, after
// GlyphWiki; covers every CJK extension) to exactly the characters the
// Chinese sources use: web/scripts/chinese-font.py, which lists them in
// fonts/Jigmo-Chinese.txt. Re-run it when a Chinese source changes.
const chineseFallback = localFont({
  src: "./fonts/Jigmo-Chinese.woff2",
  weight: "400",
  variable: "--font-chinese-fallback",
  preload: false,
  adjustFontFallback: false,
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

// Old Irish (#225, #544), Old English, Old High German and Old Saxon (#564)
// are Latin script in the body font; this backs them with what Google's Noto
// Serif slices lack (the Tironian et ⁊, the reversed c ↄ, a letter + a
// combining mark the latin slices don't carry: dot above U+0307, circumflex
// U+0302, acute U+0301, breve, caron): Noto Serif cut to Latin with its marks
// and signs in one file (web/scripts/medieval-font.py), so such a cluster
// falls back whole, in the same design.
const medievalFallback = localFont({
  src: "./fonts/NotoSerif-Medieval.woff2",
  weight: "400",
  variable: "--font-medieval-fallback",
  preload: false,
  adjustFontFallback: false,
});

// The landing page's Old Irish tile only (#544): Segotia, a Gaelic type by
// Dominic Stanley (OFL 1.1, Reserved Font Name "Segotia"), served as the
// upstream WOFF2, unmodified, from insert-smiley/Irishfontclub-segotia at
// 9462ce85bb143b5c14ac9dc9d707922fe3f017d1. Corpus text never uses it.
const insular = localFont({
  src: "./fonts/Segotia-Regular.woff2",
  weight: "400",
  variable: "--font-insular",
  preload: false,
  adjustFontFallback: false,
});

// Runes inside Old English text (#564): ASPR prints Cynewulf's signatures, the
// Rune Poem and Solomon and Saturn's runes as Unicode futhorc (U+16A0–16FF),
// which neither Noto Serif nor the medieval fallback has. Noto Sans Runic cut
// to the Runic block (7 KB, web/scripts/runic-font.py), after the medieval
// fallback in the :lang() stack. Self-hosted because next/font/google adds a
// local(Arial) fallback face to the variable even with adjustFontFallback
// off, and that Arial would sit ahead of the body font's script fonts.
const runic = localFont({
  src: "./fonts/NotoSansRunic-Runes.woff2",
  weight: "400",
  variable: "--font-runic",
  preload: false,
  adjustFontFallback: false,
});

// The landing page's Old Saxon and Old High German tiles only (#564):
// UnifrakturMaguntia, a blackletter by j. 'mach' wust after Peter Wiegel
// (OFL 1.1, Reserved Font Name "UnifrakturMaguntia"), served as Google Fonts
// serves it. Corpus text never uses it.
const fraktur = UnifrakturMaguntia({
  subsets: ["latin"],
  weight: "400",
  variable: "--font-fraktur",
  preload: false,
});

// The landing page's Old English tile only (#564): BabelStone Englisc by
// Andrew West, after the Anglo-Saxon type cut for Franciscus Junius (c. 1655),
// with insular letter shapes and wynn ƿ (Segotia has none). OFL 1.1, Reserved
// Font Name "BabelStone"; the upstream WOFF2 (version 1.000, 2023-06-24, from
// babelstone.co.uk/Fonts/WOFF/) is served unmodified. Corpus text never uses it.
const englisc = localFont({
  src: "./fonts/BabelStoneEnglisc.woff2",
  weight: "400",
  variable: "--font-englisc",
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
  georgian,
  chinese,
  chineseFallback,
  slavonic,
  slavonicFallback,
  medievalFallback,
  runic,
  insular,
  englisc,
  fraktur,
]
  .map((f) => f.variable)
  .join(" ");
