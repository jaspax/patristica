// Corpus languages: ISO 639-3 codes as stored in Work.language / Chunk.language
// (patristica/models.py), mapped to what the browser needs.

export type LanguageCode = "grc" | "lat" | "hbo" | "syc" | "cop" | "gez" | "hye" | "got" | "chu" | "eng";

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
  eng: { lang: "en", name: "English", dir: "ltr" },
};

/** Info for a corpus language code; unknown codes are passed through as LTR. */
export function languageInfo(code: string): LanguageInfo {
  return LANGUAGES[code as LanguageCode] ?? { lang: code, name: code, dir: "ltr" };
}
