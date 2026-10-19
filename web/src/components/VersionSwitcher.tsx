"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useId, useState, type MouseEvent, type ReactNode } from "react";

import { GENRES, LICENSES } from "@/lib/format";
import { languageInfo } from "@/lib/lang";
import { workHref, type WorkRow } from "@/lib/library";
import { groupByLanguage, refHash } from "@/lib/versions";

import styles from "./VersionSwitcher.module.css";

/** Where to open a version: a ref to scroll to, or null for the top. */
export type PositionFor = (target: WorkRow) => Promise<string | null>;

/** More other versions than this are listed under language headings. */
export const GROUP_BY_LANGUAGE_ABOVE = 4;

function isModified(e: MouseEvent): boolean {
  return e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey;
}

interface VersionLinkProps {
  target: WorkRow;
  positionFor?: PositionFor;
  children: ReactNode;
  "aria-describedby"?: string;
}

/**
 * A link to another version of the work. Its href opens the version at the
 * top (so it works in a new tab); a plain click asks `positionFor` where the
 * reader is and opens the version there.
 */
export function VersionLink({ target, positionFor, children, ...rest }: VersionLinkProps) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const href = workHref(target.id);

  const onClick = (e: MouseEvent<HTMLAnchorElement>) => {
    if (!positionFor || isModified(e)) return;
    e.preventDefault();
    setBusy(true);
    positionFor(target)
      .catch(() => null)
      .then((ref) => router.push(`${href}${refHash(ref)}`))
      .finally(() => setBusy(false));
  };

  return (
    <Link href={href} onClick={onClick} aria-busy={busy || undefined} className={busy ? styles.busy : undefined} {...rest}>
      {children}
    </Link>
  );
}

interface Props {
  /** The work being read. */
  current: WorkRow;
  /** Its version group, `current` included (lib/versions.ts versionMembers). */
  members: readonly WorkRow[];
  /** Ids of the originals (lib/versions.ts originalIds). */
  originals: ReadonlySet<string>;
  /** source_id → collection label (index.json). */
  sources: Record<string, string>;
  positionFor?: PositionFor;
}

/**
 * "Other versions": every other member of the work's version group, with its
 * language, collection, title, edition and licence, and the original marked.
 * Long lists are grouped by language.
 */
export default function VersionSwitcher({ current, members, originals, sources, positionFor }: Props) {
  const others = members.filter((w) => w.id !== current.id);
  const groups = groupByLanguage(others, originals, sources);
  if (others.length === 0) return null;
  const grouped = others.length > GROUP_BY_LANGUAGE_ABOVE;
  const languages = groups.length;

  const entry = (w: WorkRow) => (
    <VersionEntry
      key={w.id}
      work={w}
      current={current}
      original={originals.has(w.id)}
      label={sources[w.source_id] ?? w.source_id}
      showLanguage={!grouped}
      positionFor={positionFor}
    />
  );

  return (
    <details className={styles.versions}>
      <summary>
        Other versions ({others.length}
        {languages > 1 ? ` in ${languages} languages` : ""})
      </summary>
      {grouped ? (
        groups.map((g) => <LanguageList key={g.language} name={g.name}>{g.works.map(entry)}</LanguageList>)
      ) : (
        <ul className={styles.list}>{groups.flatMap((g) => g.works).map(entry)}</ul>
      )}
    </details>
  );
}

function LanguageList({ name, children }: { name: string; children: ReactNode }) {
  const id = useId();
  return (
    <div className={styles.group}>
      <p id={id} className={styles.language}>
        {name}
      </p>
      <ul className={styles.list} aria-labelledby={id}>
        {children}
      </ul>
    </div>
  );
}

interface EntryProps {
  work: WorkRow;
  current: WorkRow;
  original: boolean;
  label: string;
  showLanguage: boolean;
  positionFor?: PositionFor;
}

function VersionEntry({ work, current, original, label, showLanguage, positionFor }: EntryProps) {
  const id = useId();
  const lang = languageInfo(work.language);
  const license = LICENSES[work.license]?.label ?? work.license;
  const facts: ReactNode[] = [];
  if (showLanguage) facts.push(lang.name);
  if (work.title !== current.title) {
    facts.push(
      <span lang={lang.lang} dir="auto">
        {work.title}
      </span>,
    );
  }
  // Edition codes such as "1st1K-grc1" say nothing a reader can use.
  if (work.edition && /\s/.test(work.edition)) facts.push(work.edition);
  if (work.genre !== current.genre) facts.push(GENRES[work.genre] ?? work.genre);
  facts.push(license);

  return (
    <li className={styles.entry}>
      <VersionLink target={work} positionFor={positionFor} aria-describedby={id}>
        {label}
      </VersionLink>
      {original && <span className={styles.badge}>Original</span>}
      <span id={id} className={styles.facts}>
        {facts.map((f, i) => (
          <span key={i}>
            {i > 0 && <span aria-hidden="true"> · </span>}
            {i > 0 && <span className="visually-hidden">, </span>}
            {f}
          </span>
        ))}
      </span>
    </li>
  );
}
