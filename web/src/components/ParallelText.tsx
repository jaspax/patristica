"use client";

import { memo, useCallback, useMemo, useRef, type CSSProperties, type ReactNode, type RefObject } from "react";

import { unitRef } from "@/lib/alignment";
import { languageInfo } from "@/lib/lang";
import type { WorkFile, WorkRow } from "@/lib/library";
import { sectionBlocks, type Row, type Span } from "@/lib/parallel";
import { chunkRoles, parseWork, type ChunkRole, type Section } from "@/lib/render";
import { useHashTarget } from "@/lib/useHashTarget";

import styles from "./ParallelText.module.css";

const DERIVED_TITLE =
  "Verse numbers in this style are added by Patristica to make search results precise; they are not part of the source edition.";

/** One version shown in parallel. */
export interface ParallelColumn {
  row: WorkRow;
  work: WorkFile;
  /** Short name for the column: its language, plus the collection where two columns share one. */
  name: string;
}

interface Props {
  /** The columns, the leading version first. */
  columns: readonly ParallelColumn[];
  rows: readonly Row[];
  /** The element whose passages `currentPosition` reads (the leading version's ids are inside it). */
  textRef?: RefObject<HTMLDivElement | null>;
}

interface Prepared {
  column: ParallelColumn;
  sections: Section[];
  roles: ChunkRole[];
  lang: string;
  dir: "ltr" | "rtl";
  lead: boolean;
}

const COLUMN_STYLES: CSSProperties[] = Array.from({ length: 8 }, (_, c) => ({ "--col": `var(--col-${c})` }) as CSSProperties);

/** The column's colour (`--col`, from the `--col-N` palette in the CSS modules). */
export function columnStyle(c: number): CSSProperties {
  return COLUMN_STYLES[c] ?? COLUMN_STYLES[0];
}

/**
 * Rows per chunk in a long section. A work with one section of 45,000 rows
 * (Augustine's Enarrationes in PL 36) otherwise lays out every row's
 * placeholder on each long jump (~0.6 s a frame, measured); chunks skip as
 * a whole, like the sections.
 */
export const ROWS_PER_CHUNK = 64;

/** [from, to) row ranges of ROWS_PER_CHUNK. */
function chunked(n: number): [number, number][] {
  const out: [number, number][] = [];
  for (let from = 0; from < n; from += ROWS_PER_CHUNK) out.push([from, Math.min(n, from + ROWS_PER_CHUNK)]);
  return out;
}

/** Escape a value for a double-quoted CSS attribute selector. */
function attrValue(value: string): string {
  return value.replace(/["\\]/g, "\\$&");
}

/**
 * The versions side by side (#181): the leading version's sections, each a
 * list of rows; each row holds one alignment group's units in every version
 * (lib/parallel.ts). Only the leading version's elements carry ids (refs are
 * often the same across versions); the others carry `data-ref`, and a
 * fragment that isn't the leading version's is looked up there.
 */
export default function ParallelText({ columns, rows, textRef }: Props) {
  const prepared = useMemo<Prepared[]>(
    () =>
      columns.map((column, c) => {
        const info = languageInfo(column.row.language);
        const sections = parseWork(column.work, column.row.genre, column.row.source_id);
        return {
          column,
          sections,
          roles: chunkRoles(column.work, sections),
          lang: info.lang,
          dir: info.dir,
          lead: c === 0,
        };
      }),
    [columns],
  );
  const leadSections = prepared[0].sections;
  const blocks = useMemo(() => sectionBlocks(rows, leadSections, prepared[0].roles), [rows, leadSections, prepared]);
  const toc = leadSections.filter((s) => s.title ?? s.label);
  const lead = prepared[0];

  const ownRef = useRef<HTMLDivElement | null>(null);
  const root = textRef ?? ownRef;
  const resolve = useCallback(
    (id: string) =>
      document.getElementById(id) ?? root.current?.querySelector(`[data-ref="${attrValue(id)}"]`) ?? null,
    [root],
  );
  useHashTarget(blocks.length > 0, resolve);

  return (
    <div className={styles.parallel} style={{ "--cols": columns.length } as CSSProperties}>
      {toc.length > 1 && (
        <details className={styles.toc}>
          <summary>Contents ({toc.length} sections)</summary>
          <ol>
            {toc.map((s) => (
              <li key={s.id} style={{ paddingInlineStart: `${s.depth}rem` }}>
                <a href={`#${s.id}`} lang={lead.lang} dir="auto">
                  {s.title ?? s.label}
                </a>
              </li>
            ))}
          </ol>
        </details>
      )}
      {/* Column names, kept in view while reading (wide screens). */}
      <div className={styles.heads} aria-hidden="true">
        {prepared.map((p, c) => (
          <div key={p.column.row.id} className={styles.head} data-col={c} style={columnStyle(c)}>
            {p.column.name}
          </div>
        ))}
      </div>
      <div className={styles.text} ref={root}>
        {blocks.map((b) => (
          <section key={b.section.id} id={b.section.id} className={styles.section}>
            {b.section.title === null && b.section.label && <h2 className={styles.label}>{b.section.label}</h2>}
            {chunked(b.rows.length).map(([from, to]) => {
              const rowViews = b.rows
                .slice(from, to)
                .map((r, k) => (
                  <RowView key={r.key} row={r} starts={b.starts[from + k]} prepared={prepared} leadLabel={b.section.label} />
                ));
              // Long sections are cut into chunks of rows that skip layout as a whole.
              return b.rows.length > ROWS_PER_CHUNK ? (
                <div key={from} className={styles.chunk} data-chunk="">
                  {rowViews}
                </div>
              ) : (
                rowViews
              );
            })}
          </section>
        ))}
      </div>
    </div>
  );
}

interface RowProps {
  row: Row;
  starts: string[];
  prepared: Prepared[];
  leadLabel: string | null;
}

const RowView = memo(function RowView({ row, starts, prepared, leadLabel }: RowProps) {
  const uncertain = row.uncertain.some(Boolean);
  return (
    <div className={styles.row} data-uncertain={uncertain || undefined}>
      {starts.map((id) => (
        <span key={id} id={id} className={styles.anchor} />
      ))}
      {prepared.map((p, c) => {
        const span = row.cells[c];
        if (!span) return <div key={c} className={styles.empty} aria-hidden="true" />;
        return (
          <div key={c} className={styles.cell} data-col={c} style={columnStyle(c)} lang={p.lang} dir={p.dir}>
            <span className={styles.cellLabel} lang="en" dir="ltr">
              {p.column.name}
              <span className="visually-hidden">: </span>
            </span>
            {row.uncertain[c] && (
              <span className={styles.uncertain} lang="en" dir="ltr" title="The alignment of this passage with the others is uncertain">
                uncertain alignment
              </span>
            )}
            {cellContent(p, span, leadLabel)}
          </div>
        );
      })}
    </div>
  );
});

function idProps(p: Prepared, ref: string): { id?: string; "data-ref"?: string } {
  return p.lead ? { id: ref } : { "data-ref": ref };
}

/**
 * The units of `span` in one version: headings, paragraphs (or verses), and
 * derived verses joined per paragraph. Where another Scripture version starts
 * a chapter of its own numbering (the Vulgate's Psalm 22 beside the KJV's
 * 23), its label is shown unless it matches `leadLabel`, the leading
 * version's section label.
 */
function cellContent(p: Prepared, [start, end]: Span, leadLabel: string | null): ReactNode[] {
  const { work } = p.column;
  const out: ReactNode[] = [];
  for (let i = start; i < end; ) {
    const role = p.roles[i];
    const ref = unitRef(work, i);
    if (!p.lead && p.column.row.genre === "scripture" && role && role.kind !== "heading" && (role.kind === "unit" || role.part === 0)) {
      const section = p.sections[role.sectionIndex];
      if (section.units[0] === role.unit && section.title === null && section.label && section.label !== leadLabel) {
        out.push(
          <p key={`l${i}`} className={styles.sublabel}>
            {section.label}
          </p>,
        );
      }
    }
    if (!role) {
      out.push(
        <p key={i} className={styles.para} {...idProps(p, ref)}>
          {work.chunks[i][1]}
        </p>,
      );
      i += 1;
    } else if (role.kind === "heading") {
      const text = role.section.title ?? work.chunks[i][1];
      if (p.lead) {
        const Heading = (["h2", "h3", "h4"] as const)[Math.min(role.section.depth, 2)];
        out.push(
          <Heading key={i} className={styles.title} id={ref}>
            {text}
          </Heading>,
        );
      } else {
        out.push(
          <p key={i} className={styles.title} data-ref={ref}>
            {text}
          </p>,
        );
      }
      i += 1;
    } else if (role.kind === "unit") {
      const u = role.unit;
      const classes = [styles.para, u.rubric && styles.rubric, u.outOfPeriod && styles.oop].filter(Boolean).join(" ");
      out.push(
        <p key={i} className={classes} {...idProps(p, ref)} title={u.outOfPeriod ? "After the collection period" : undefined}>
          <a className={styles.marker} href={`#${ref}`} aria-label={`Paragraph ${u.n}`}>
            {u.n}
          </a>
          {u.text}
        </p>,
      );
      i += 1;
    } else {
      // Derived verses of one paragraph, as far as this span has them.
      const u = role.unit;
      const first = role.part;
      const sameUnit = (r: ChunkRole | undefined) => r?.kind === "part" && r.unit === u;
      let j = i;
      while (j < end && sameUnit(p.roles[j])) j++;
      const parts = u.parts!.slice(first, first + (j - i));
      const classes = [styles.para, u.outOfPeriod && styles.oop].filter(Boolean).join(" ");
      out.push(
        <p key={i} className={classes} {...(first === 0 ? idProps(p, u.ref) : {})}>
          {first === 0 && (
            <a className={styles.marker} href={`#${u.ref}`} aria-label={`Paragraph ${u.n}`}>
              {u.n}
            </a>
          )}
          {parts.map((part, k) => (
            <span key={part.ref} {...idProps(p, part.ref)}>
              {k > 0 && " "}
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
          ))}
        </p>,
      );
      i = j;
    }
  }
  return out;
}
