"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { languageInfo } from "@/lib/lang";
import { type LibraryIndex, loadIndex } from "@/lib/library";
import { useLoaded } from "@/lib/useLoaded";

import styles from "./Landing.module.css";

/**
 * The top of the landing page: what Patristica is, over the header image.
 * It renders on the server too (as the search page's loading fallback), so it uses no hooks.
 */
export function Hero() {
  return (
    <section className={styles.hero} aria-labelledby="hero-title">
      <div className={styles.heroText}>
        <p className={styles.eyebrow}>Scripture · Fathers · Councils · Liturgy</p>
        <h1 id="hero-title" className={styles.title}>
          The Christian writings of the first thousand years, in their own words
        </h1>
        <p className={styles.lead}>
          Patristica is a free library of Scripture and the early Church: the Fathers, the councils and the
          liturgies, from the apostles to the eleventh century, in the original Greek, Latin, Hebrew, Syriac,
          Coptic, Ge&lsquo;ez, Armenian and Gothic, with English translations alongside.
        </p>
        <p className={styles.lead}>
          Search it by idea or by exact phrase, read each text whole, and follow a passage across its
          translations, whether you are checking a citation, preparing a homily, or simply curious what the
          early Christians wrote.
        </p>
      </div>
    </section>
  );
}

/** Example searches; each is a link that runs it. */
const EXAMPLES = [
  "Christ as physician of the soul",
  "baptism of desire",
  "the light of Tabor",
  '"in principio erat verbum"',
];

/**
 * "The Word" in each language of the collection, from John 1:1, with the
 * exact-phrase search that finds it. The corpus has Gothic in transliteration,
 * and a Ge'ez phrase needs three letters, hence "and the Word" there.
 */
const WORDS: { language: string; word: string; query: string }[] = [
  { language: "grc", word: "λόγος", query: "λόγος" },
  { language: "lat", word: "verbum", query: "verbum" },
  { language: "hbo", word: "דָּבָר", query: "דָּבָר" },
  { language: "syc", word: "ܡܠܬܐ", query: "ܡܠܬܐ" },
  { language: "cop", word: "ϣⲁϫⲉ", query: "ϣⲁϫⲉ" },
  { language: "gez", word: "ወቃል", query: "ወቃል" },
  { language: "hye", word: "բան", query: "բան" },
  { language: "got", word: "𐍅𐌰𐌿𐍂𐌳", query: "waurd" },
];

/** The search page's link for a query. */
export function searchHref(q: string): string {
  return `/?${new URLSearchParams({ q })}`;
}

/** What the landing page shows below the search box when there is no query. */
export default function Landing() {
  return (
    <div className={styles.landing}>
      <p className={styles.examples}>
        <span className={styles.examplesLabel}>Try:</span>
        {EXAMPLES.map((q) => (
          <Link key={q} href={searchHref(q)} className={styles.chip}>
            {q}
          </Link>
        ))}
      </p>

      <Stats />

      <ul className={styles.features}>
        <li>
          <FeatureIcon kind="meaning" />
          <h2>Search by meaning</h2>
          <p>
            Describe an idea in plain English, or in any language, and the passages closest to it come
            first, whatever words they use.
          </p>
        </li>
        <li>
          <FeatureIcon kind="phrase" />
          <h2>Trace a phrase</h2>
          <p>
            Put words in quotes to find every place they occur. Accents, breathings and spelling variants
            don&rsquo;t matter, so a verse can be followed through the Fathers who quote it.
          </p>
        </li>
        <li>
          <FeatureIcon kind="read" />
          <h2>Read the whole text</h2>
          <p>
            Every result opens in its full work. Where a text survives in several languages or editions,{" "}
            <Link href="/works">read them side by side</Link>.
          </p>
        </li>
      </ul>

      <section className={styles.words} aria-labelledby="words-title">
        <h2 id="words-title">
          <span className={styles.wordsQuote}>In the beginning was the Word</span>
          <span className={styles.wordsSub}>…in each language of the collection. Choose one to find it.</span>
        </h2>
        <ul>
          {WORDS.map(({ language, word, query }) => {
            const lang = languageInfo(language);
            return (
              <li key={language}>
                <Link href={searchHref(`"${query}"`)} className={styles.word}>
                  <span lang={lang.lang} dir={lang.dir} className={styles.wordText}>
                    {word}
                  </span>
                  <span className={styles.wordLang}>{lang.name}</span>
                </Link>
              </li>
            );
          })}
        </ul>
      </section>
    </div>
  );
}

/** Counts shown under the examples, from the library index. */
export function libraryStats(index: LibraryIndex): { label: string; value: number }[] {
  const authors = new Set(index.works.flatMap((w) => w.author_ids));
  const languages = new Set(index.works.map((w) => w.language));
  const passages = index.works.reduce((n, w) => n + w.chunks, 0);
  return [
    { label: "works", value: index.works.length },
    { label: "authors", value: authors.size },
    { label: "languages", value: languages.size },
    { label: "passages", value: passages },
  ];
}

function Stats() {
  const index = useLoaded(loadIndex);
  const stats = useMemo(() => (index.status === "ready" ? libraryStats(index.data) : null), [index]);
  // Reserve the line while loading so the page doesn't jump; say nothing if the index fails.
  if (index.status === "error") return null;
  return (
    <dl className={styles.stats} aria-busy={!stats}>
      {(stats ?? libraryStats({ version: "", sources: {}, works: [] })).map(({ label, value }) => (
        <div key={label}>
          <dt>{label}</dt>
          <dd>{stats ? <CountUp value={value} /> : "—"}</dd>
        </div>
      ))}
    </dl>
  );
}

/** Whether the reader asked for less motion (true where matchMedia is missing, as in tests). */
function reducedMotion(): boolean {
  return typeof window.matchMedia !== "function" || window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

/** A number that counts up from zero when it first appears. */
function CountUp({ value, ms = 900 }: { value: number; ms?: number }) {
  // Progress of the animation, 0 to 1; with reduced motion it starts at the end.
  const [progress, setProgress] = useState(() => (reducedMotion() ? 1 : 0));
  useEffect(() => {
    if (reducedMotion()) return;
    const start = performance.now();
    let frame = 0;
    const step = (now: number) => {
      const t = Math.min(1, (now - start) / ms);
      setProgress(t);
      if (t < 1) frame = requestAnimationFrame(step);
    };
    frame = requestAnimationFrame(step);
    return () => cancelAnimationFrame(frame);
  }, [value, ms]);
  const shown = Math.round(value * (1 - (1 - progress) ** 3));
  // Screen readers get the final number, not the animation.
  return (
    <>
      <span aria-hidden="true">{shown.toLocaleString("en")}</span>
      <span className="visually-hidden">{value.toLocaleString("en")}</span>
    </>
  );
}

function FeatureIcon({ kind }: { kind: "meaning" | "phrase" | "read" }) {
  const paths = {
    // A lamp: searching by the light of meaning.
    meaning: (
      <>
        <path d="M4 17c0-2.5 3.5-4 8-4s8 1.5 8 4c0 1.2-1.5 2-4 2H8c-2.5 0-4-.8-4-2z" />
        <path d="M20 17c1.5 0 2.5-.8 2.5-2" />
        <path d="M12 13c-1.2-1.6-1.2-3.4 0-5.5 1.2 2.1 1.2 3.9 0 5.5z" />
        <path d="M9 21h6" />
      </>
    ),
    // Quotation marks.
    phrase: (
      <>
        <path d="M5 16c0-4 1.5-7 5-9" />
        <path d="M5 16a2.5 2.5 0 1 0 5 0 2.5 2.5 0 1 0-5 0" />
        <path d="M14 16c0-4 1.5-7 5-9" />
        <path d="M14 16a2.5 2.5 0 1 0 5 0 2.5 2.5 0 1 0-5 0" />
      </>
    ),
    // An open codex.
    read: (
      <>
        <path d="M12 6.5C10 5 7 4.5 3 5v13c4-.5 7 0 9 1.5" />
        <path d="M12 6.5C14 5 17 4.5 21 5v13c-4-.5-7 0-9 1.5z" />
        <path d="M6 9h3M6 12h3M15 9h3M15 12h3" />
      </>
    ),
  }[kind];
  return (
    <svg
      className={styles.featureIcon}
      viewBox="0 0 24 24"
      aria-hidden="true"
      focusable="false"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      {paths}
    </svg>
  );
}
