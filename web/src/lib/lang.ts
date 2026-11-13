// Corpus languages: ISO 639-3 codes as stored in Work.language / Chunk.language
// (patristica/models.py), mapped to what the browser needs.

export type LanguageCode = "grc" | "lat" | "hbo" | "syc" | "cop" | "gez" | "hye" | "got" | "chu" | "arb" | "oge" | "sga" | "ang" | "goh" | "osx" | "lzh" | "eng";

export interface LanguageInfo {
  /** BCP 47 tag for the `lang` attribute; globals.css selects fonts with :lang(). */
  lang: string;
  /** Display name. */
  name: string;
  dir: "ltr" | "rtl";
}

export const LANGUAGES: Record<LanguageCode, LanguageInfo> = {
  grc: { lang: "grc", name: "Greek", dir: "ltr" },
  lat: { lang: "la", name: "Latin", dir: "ltr" },
  hbo: { lang: "hbo", name: "Hebrew", dir: "rtl" },
  syc: { lang: "syc", name: "Syriac", dir: "rtl" },
  cop: { lang: "cop", name: "Coptic", dir: "ltr" },
  gez: { lang: "gez", name: "Ge'ez", dir: "ltr" },
  hye: { lang: "hy", name: "Armenian", dir: "ltr" },
  got: { lang: "got", name: "Gothic", dir: "ltr" },
  chu: { lang: "cu", name: "Church Slavonic", dir: "ltr" },
  arb: { lang: "ar", name: "Arabic", dir: "rtl" },
  // BCP 47 "oge" is Old Georgian; "ka" would be modern Georgian.
  oge: { lang: "oge", name: "Old Georgian", dir: "ltr" },
  // Old Irish (c. 600–900): "sga" in both ISO 639-3 and BCP 47; "ga" is modern Irish.
  sga: { lang: "sga", name: "Old Irish", dir: "ltr" },
  // Old English, Old High German and Old Saxon (#223, #224): the same codes in
  // ISO 639-3 and BCP 47 ("en" and "de" would be the modern languages).
  ang: { lang: "ang", name: "Old English", dir: "ltr" },
  goh: { lang: "goh", name: "Old High German", dir: "ltr" },
  osx: { lang: "osx", name: "Old Saxon", dir: "ltr" },
  // Literary Chinese (#228): "lzh" in both ISO 639-3 and BCP 47 ("zh" would be
  // modern Chinese). Set horizontally; globals.css picks Noto Serif TC.
  lzh: { lang: "lzh", name: "Literary Chinese", dir: "ltr" },
  eng: { lang: "en", name: "English", dir: "ltr" },
};

/** Info for a corpus language code; unknown codes are passed through as LTR. */
export function languageInfo(code: string): LanguageInfo {
  return LANGUAGES[code as LanguageCode] ?? { lang: code, name: code, dir: "ltr" };
}
