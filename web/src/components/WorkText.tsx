"use client";

import { useMemo } from "react";

import { languageInfo } from "@/lib/lang";
import type { WorkFile } from "@/lib/library";
import { parseWork, type Section, type Unit } from "@/lib/render";
import { useHashTarget } from "@/lib/useHashTarget";

import styles from "./WorkText.module.css";

const DERIVED_TITLE =
  "Verse numbers in this style are added by Patristica to make search results precise; they are not part of the source edition.";

interface Props {
  work: WorkFile;
  genre: string;
  language: string;
  sourceId: string;
}

/** The text of a work, rendered from its normalized chunks (see lib/render.ts). */
export default function WorkText({ work, genre, language, sourceId }: Props) {
  const sections = useMemo(() => parseWork(work, genre, sourceId), [work, genre, sourceId]);
  const lang = languageInfo(language);
  const inline = genre === "scripture";
  const toc = sections.filter((s) => s.title ?? s.label);
  // Search results link to `#{ref}`; jump there once the text is on the page.
  useHashTarget(sections.length > 0);

  return (
    <div lang={lang.lang} dir={lang.dir}>
      {toc.length > 1 && (
        <details className={styles.toc} dir="ltr" lang="en">
          <summary>Contents ({toc.length} sections)</summary>
          <ol>
            {toc.map((s) => (
              <li key={s.id} style={{ paddingInlineStart: `${s.depth}rem` }}>
                <a href={`#${s.id}`} lang={lang.lang} dir="auto">
                  {s.title ?? s.label}
                </a>
              </li>
            ))}
          </ol>
        </details>
      )}
      <div className={styles.text}>
        {sections.map((s) => (
          <SectionView key={s.id} section={s} inline={inline} />
        ))}
      </div>
    </div>
  );
}

function SectionView({ section, inline }: { section: Section; inline: boolean }) {
  const heading = section.title ?? section.label;
  const Heading = (["h2", "h3", "h4"] as const)[Math.min(section.depth, 2)];
  return (
    <section id={section.id} className={styles.section}>
      {heading && (
        <Heading id={section.ref ?? undefined} className={section.title ? styles.title : styles.label}>
          {heading}
        </Heading>
      )}
      {inline ? (
        <p className={styles.verses}>
          {section.units.map((u, i) => (
            <span key={i} id={u.ref} className={u.outOfPeriod ? styles.oop : undefined}>
              <sup className={styles.n}>{u.n}</sup>
              {u.text}{" "}
            </span>
          ))}
        </p>
      ) : (
        section.units.map((u, i) => <Paragraph key={i} unit={u} />)
      )}
    </section>
  );
}

function Paragraph({ unit }: { unit: Unit }) {
  const classes = [styles.para, unit.rubric && styles.rubric, unit.outOfPeriod && styles.oop]
    .filter(Boolean)
    .join(" ");
  return (
    <p id={unit.ref} className={classes} title={unit.outOfPeriod ? "After the collection period" : undefined}>
      <a className={styles.marker} href={`#${unit.ref}`} aria-label={`Paragraph ${unit.n}`}>
        {unit.n}
      </a>
      {unit.parts
        ? unit.parts.map((part, i) => (
            <span key={part.ref} id={part.ref}>
              {i > 0 && " "}
              <a
                className={styles.derived}
                href={`#${part.ref}`}
                title={DERIVED_TITLE}
                aria-label={`Verse ${part.n}, added by Patristica`}
                dir="ltr"
                lang="en"
              >
                {part.n}
              </a>
              {part.text}
            </span>
          ))
        : unit.text}
    </p>
  );
}
