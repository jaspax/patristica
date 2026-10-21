// Fonts for every script in the corpus, exposed as CSS variables.
// Only the body font is preloaded; the script fonts load on demand through
// their unicode-range when a page uses them. globals.css picks the font per
// language with :lang() rules (see lib/lang.ts for the lang values).
import {
  Cinzel,
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

/** Class names that define all font CSS variables; put on <html>. */
export const fontVariables = [serif, display, hebrew, syriac, coptic, ethiopic, armenian, gothic]
  .map((f) => f.variable)
  .join(" ");
