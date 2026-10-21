"use client";

import Link from "next/link";
import { useCallback, useMemo, useRef, type CSSProperties } from "react";

import { LICENSES } from "@/lib/format";
import { languageInfo } from "@/lib/lang";
import {
  hasAlignment,
  loadAlignment,
  loadWork,
  workAuthors,
  workHref,
  type Library,
  type LibraryIndex,
  type WorkFile,
  type WorkRow,
} from "@/lib/library";
import {
  alignmentMembers,
  buildRows,
  isScriptureBook,
  keepPosition,
  MAX_VERSIONS,
  parallelHref,
  parallelVersions,
  splitColumnRef,
  versificationMembers,
  type ColumnPosition,
  type Row,
} from "@/lib/parallel";
import { NON_COMMERCIAL } from "@/lib/sources";
import { useLoaded } from "@/lib/useLoaded";
import {
  currentPosition,
  distinguishVersions,
  groupByLanguage,
  originalIds,
  positionIn,
  versionMembers,
  type Position,
} from "@/lib/versions";

import AuthorLinks from "./AuthorLinks";
import LoadError from "./LoadError";
import ParallelText, { columnStyle, type ParallelColumn } from "./ParallelText";
import styles from "./ParallelReader.module.css";
import { PositionLink } from "./VersionSwitcher";

interface Props {
  lead: WorkRow;
  /** The `with` ids of the URL. */
  withIds: readonly string[];
  library: Library;
}

interface Loaded {
  columns: ParallelColumn[];
  rows: Row[];
  /** Versions asked for that the alignment doesn't cover (left out as stale). */
  unaligned: WorkRow[];
}

/** Column names: the language, plus the collection where two columns share a language. */
export function columnNames(rows: readonly WorkRow[], sources: Record<string, string>): string[] {
  return rows.map((r) => {
    const name = languageInfo(r.language).name;
    const shared = rows.filter((o) => o.language === r.language).length > 1;
    return shared ? `${name} · ${sources[r.source_id] ?? r.source_id}` : name;
  });
}

/**
 * Load the versions and build the rows: Scripture books by versification
 * (org_refs), other works by their version group's passage alignment. A
 * version the alignment leaves out is dropped (and reported).
 */
export async function loadParallel(index: LibraryIndex, wanted: readonly WorkRow[]): Promise<Loaded | null> {
  const works = await Promise.all(wanted.map((w) => loadWork(w.file)));
  const lead = wanted[0];
  let members;
  if (isScriptureBook(lead)) {
    members = versificationMembers(works);
  } else if (hasAlignment(index, lead.version_group)) {
    members = alignmentMembers(await loadAlignment(lead.version_group), wanted, works);
  } else {
    return null;
  }
  if (!members[0]) return null;
  const keep = wanted.map((_, c) => members[c] !== null);
  const rows = wanted.filter((_, c) => keep[c]);
  const names = columnNames(rows, index.sources);
  const kept: { row: WorkRow; work: WorkFile }[] = wanted
    .map((row, c) => ({ row, work: works[c] }))
    .filter((_, c) => keep[c]);
  return {
    columns: kept.map((k, c) => ({ ...k, name: names[c] })),
    rows: buildRows(members.filter((m) => m !== null)),
    unaligned: wanted.filter((_, c) => !keep[c]),
  };
}

/**
 * Parallel reading (#181): `lead` with the versions `withIds` names beside it
 * (`/works/{lead}?with=…`). The header names the versions, with each one's
 * edition and licence, and links to add, remove or lead with a version, or
 * to go back to reading one; every link keeps the reader's place.
 */
export default function ParallelReader({ lead, withIds, library }: Props) {
  const { index, authors } = library;
  const { columns: wanted, skipped } = useMemo(() => parallelVersions(index, lead, withIds), [index, lead, withIds]);
  const data = useLoaded(() => loadParallel(index, wanted));
  const textRef = useRef<HTMLDivElement>(null);

  const members = useMemo(() => versionMembers(index, lead), [index, lead]);
  const originals = useMemo(() => originalIds(members), [members]);
  const lang = languageInfo(lead.language);
  const byline = workAuthors(lead, authors);
  const names = byline.map((a) => a.name).join(", ");
  const collection = index.sources[lead.source_id] ?? lead.source_id;

  const ready = data.status === "ready" && data.data ? data.data : null;
  const shown = useMemo(() => ready?.columns.map((c) => c.row) ?? wanted, [ready, wanted]);

  // Where the reader is: a passage in any column (the fragment's while on
  // screen, else the first at the top of the viewport), with its version.
  const here = useCallback((): ColumnPosition | null => {
    if (!ready) return null;
    const p = currentPosition(textRef.current, window.location.hash);
    if (!p) return null;
    const { ref, work } = splitColumnRef(p.ref, ready.columns.map((c) => c.row.id));
    return { ref, work, highlight: p.highlight };
  }, [ready]);
  // Where to open `to` (with `others` beside it) for that passage: the same
  // passage if its version is still shown, else mapped to `to`.
  const positionFor = useCallback(
    (to: WorkRow, others: readonly string[]) => async (): Promise<Position | null> => {
      const at = here();
      if (!at || !ready) return null;
      const kept = keepPosition(at, to.id, others);
      if (kept) return kept;
      const from = ready.columns.find((c) => c.row.id === at.work)!;
      return positionIn(index, from.row, from.work, { ref: at.ref, highlight: at.highlight }, to);
    },
    [here, ready, index],
  );
  const otherIds = shown.slice(1).map((w) => w.id);

  return (
    <article className={styles.page}>
      <title>{`${names ? `${names}, ` : ""}${lead.title} (in parallel) · Patristica`}</title>
      <nav className={styles.crumbs} aria-label="Breadcrumb">
        <Link href="/works">Library</Link>
        <span aria-hidden="true"> / </span>
        <Link href={`/works?source=${encodeURIComponent(lead.source_id)}`}>{collection}</Link>
      </nav>

      <header className={styles.header}>
        <h1 lang={lang.lang} dir="auto">
          {lead.title}
        </h1>
        {byline.length > 0 && (
          <p className={styles.author} dir="auto">
            <AuthorLinks authors={byline} />
          </p>
        )}
        <p className={styles.mode}>
          Reading {shown.length} versions side by side.{" "}
          <PositionLink href={workHref(lead.id)} position={positionFor(lead, [])}>
            Back to reading one version
          </PositionLink>
        </p>
        <AddVersion
          index={index}
          lead={lead}
          members={members}
          originals={originals}
          shown={shown}
          positionFor={positionFor}
        />
        {skipped.length > 0 && (
          <ul className={styles.notice} role="status">
            {skipped.map((s) => (
              <li key={s.id}>
                <code>{s.id}</code>{" "}
                {s.reason === "unknown"
                  ? "is not in the library."
                  : s.reason === "not-a-version"
                    ? "is not a version of this work."
                    : `is left out: at most ${MAX_VERSIONS} versions fit side by side.`}
              </li>
            ))}
          </ul>
        )}
        {ready && ready.unaligned.length > 0 && (
          <p className={styles.notice} role="status">
            Not aligned with this version yet, so not shown:{" "}
            {ready.unaligned.map((w, i) => (
              <span key={w.id}>
                {i > 0 && ", "}
                <Link href={workHref(w.id)}>{index.sources[w.source_id] ?? w.source_id}</Link>
              </span>
            ))}
            .
          </p>
        )}
      </header>

      <ol className={styles.versions} style={{ "--cols": shown.length } as CSSProperties} aria-label="Versions">
        {shown.map((w, c) => (
          <VersionCard
            key={w.id}
            work={w}
            column={c}
            index={index}
            original={originals.has(w.id)}
            title={w.title !== lead.title ? w.title : null}
            open={positionFor(w, [])}
            remove={c === 0 ? null : withoutVersion(lead, otherIds, w, positionFor)}
            makeLead={c === 0 ? null : leadWith(lead, otherIds, w, positionFor)}
          />
        ))}
      </ol>

      {data.status === "loading" && <p>Loading the texts…</p>}
      {data.status === "error" && <LoadError error={data.error} />}
      {data.status === "ready" && !data.data && (
        <p className={styles.notice} role="status">
          These versions have no passage alignment yet, so they can&apos;t be read side by side.{" "}
          <Link href={workHref(lead.id)}>Read {lead.title}</Link>
        </p>
      )}
      {ready && <ParallelText columns={ready.columns} rows={ready.rows} textRef={textRef} />}
    </article>
  );
}

/** Where to open a view led by `to` with `others` beside it, keeping the reader's passage. */
type PositionFor = (to: WorkRow, others: readonly string[]) => () => Promise<Position | null>;

/** A link target: a URL and where to open it. */
interface Target {
  href: string;
  position: () => Promise<Position | null>;
}

/** The view without version `w`. */
function withoutVersion(lead: WorkRow, others: readonly string[], w: WorkRow, positionFor: PositionFor): Target {
  const rest = others.filter((id) => id !== w.id);
  return { href: parallelHref(lead.id, rest), position: positionFor(lead, rest) };
}

/** The view led by version `w`, the current leading version beside it. */
function leadWith(lead: WorkRow, others: readonly string[], w: WorkRow, positionFor: PositionFor): Target {
  const rest = [lead.id, ...others.filter((id) => id !== w.id)];
  return { href: parallelHref(w.id, rest), position: positionFor(w, rest) };
}

interface CardProps {
  work: WorkRow;
  column: number;
  index: LibraryIndex;
  original: boolean;
  /** The title, where it differs from the leading version's. */
  title: string | null;
  /** Where to open this version on its own page. */
  open: () => Promise<Position | null>;
  /** The view without this version, or null for the leading one. */
  remove: Target | null;
  /** The view with this version leading, or null for the leading one. */
  makeLead: Target | null;
}

/** One version's attribution: language, collection, edition, licence; and its controls. */
function VersionCard({ work, column, index, original, title, open, remove, makeLead }: CardProps) {
  const info = languageInfo(work.language);
  const license = LICENSES[work.license] ?? { label: work.license };
  const label = index.sources[work.source_id] ?? work.source_id;
  return (
    <li className={styles.card} data-col={column} style={columnStyle(column)}>
      <p className={styles.cardLanguage}>
        {info.name}
        {column === 0 && <span className={styles.badge}>leading</span>}
        {original && <span className={styles.badge}>Original</span>}
      </p>
      <p>
        <PositionLink href={workHref(work.id)} position={open}>
          {label}
        </PositionLink>
      </p>
      {title && (
        <p lang={info.lang} dir="auto">
          {title}
        </p>
      )}
      {work.edition && <p className={styles.muted}>{work.edition}</p>}
      <p className={styles.muted}>
        {license.url ? <a href={license.url}>{license.label}</a> : license.label}
        {NON_COMMERCIAL.has(work.license) && <span className={styles.nc}>non-commercial</span>}
      </p>
      {(remove !== null || makeLead !== null) && (
        <p className={styles.controls}>
          {makeLead && (
            <PositionLink href={makeLead.href} position={makeLead.position} aria-label={`Lead with ${info.name}: ${label}`}>
              lead with this
            </PositionLink>
          )}
          {remove && (
            <PositionLink href={remove.href} position={remove.position} aria-label={`Remove ${info.name}: ${label}`}>
              remove
            </PositionLink>
          )}
        </p>
      )}
    </li>
  );
}

interface AddProps {
  index: LibraryIndex;
  lead: WorkRow;
  members: readonly WorkRow[];
  originals: ReadonlySet<string>;
  shown: readonly WorkRow[];
  positionFor: PositionFor;
}

/** "Add a version": the group's other members, each opening the view with it added. */
function AddVersion({ index, lead, members, originals, shown, positionFor }: AddProps) {
  const ids = new Set(shown.map((w) => w.id));
  const rest = members.filter((w) => !ids.has(w.id));
  if (rest.length === 0) return null;
  if (shown.length >= MAX_VERSIONS) {
    return <p className={styles.muted}>At most {MAX_VERSIONS} versions fit side by side; remove one to add another.</p>;
  }
  const details = distinguishVersions(rest, lead, index.sources);
  const others = shown.slice(1).map((w) => w.id);
  return (
    <details className={styles.add}>
      <summary>Add a version ({rest.length} more)</summary>
      {groupByLanguage(rest, originals, index.sources).map((g) => (
        <div key={g.language} className={styles.addGroup}>
          <p className={styles.addLanguage}>{g.name}</p>
          <ul>
            {g.works.map((w) => {
              const d = details.get(w.id)!;
              return (
                <li key={w.id}>
                  <PositionLink href={parallelHref(lead.id, [...others, w.id])} position={positionFor(lead, [...others, w.id])}>
                    {index.sources[w.source_id] ?? w.source_id}
                  </PositionLink>
                  {d.title && (
                    <span className={styles.muted} lang={languageInfo(w.language).lang} dir="auto">
                      {" "}
                      · {d.title}
                    </span>
                  )}
                  {d.edition && <span className={styles.muted}> · {d.edition}</span>}
                </li>
              );
            })}
          </ul>
        </div>
      ))}
    </details>
  );
}
