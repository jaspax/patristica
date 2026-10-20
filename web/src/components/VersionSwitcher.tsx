"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  useEffect,
  useId,
  useRef,
  useState,
  type MouseEvent,
  type ReactNode,
  type Ref,
} from "react";

import { languageInfo } from "@/lib/lang";
import { workHref, type WorkRow } from "@/lib/library";
import { distinguishVersions, groupByLanguage, refHash, type VersionDetails } from "@/lib/versions";

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
 * reader is at that moment and opens the version there.
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

export interface VersionsProps {
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

/** "Other versions (9 in 7 languages)". */
export function versionsLabel(current: WorkRow, members: readonly WorkRow[]): string {
  return `Other versions (${versionsCount(current, members)})`;
}

/** "9 in 7 languages", or "1" for a single other version. */
function versionsCount(current: WorkRow, members: readonly WorkRow[]): string {
  const others = members.filter((w) => w.id !== current.id);
  const languages = new Set(others.map((w) => w.language)).size;
  return `${others.length}${languages > 1 ? ` in ${languages} languages` : ""}`;
}

/**
 * Every other member of the work's version group: language, collection
 * label, the title where it differs from the current work's, and the
 * original marked. Long lists are grouped by language.
 */
export function VersionList({ current, members, originals, sources, positionFor }: VersionsProps) {
  const others = members.filter((w) => w.id !== current.id);
  const groups = groupByLanguage(others, originals, sources);
  const details = distinguishVersions(others, current, sources);
  const grouped = others.length > GROUP_BY_LANGUAGE_ABOVE;

  const entry = (w: WorkRow) => (
    <VersionEntry
      key={w.id}
      work={w}
      details={details.get(w.id)!}
      original={originals.has(w.id)}
      label={sources[w.source_id] ?? w.source_id}
      showLanguage={!grouped}
      positionFor={positionFor}
    />
  );

  return grouped ? (
    groups.map((g) => (
      <LanguageList key={g.language} name={g.name}>
        {g.works.map(entry)}
      </LanguageList>
    ))
  ) : (
    <ul className={styles.list}>{groups.flatMap((g) => g.works).map(entry)}</ul>
  );
}

/** The header's "Other versions" disclosure. Renders nothing for a work with no other version. */
export default function VersionSwitcher({ ref, ...props }: VersionsProps & { ref?: Ref<HTMLDetailsElement> }) {
  if (!props.members.some((w) => w.id !== props.current.id)) return null;
  return (
    <details className={styles.versions} ref={ref}>
      <summary>{versionsLabel(props.current, props.members)}</summary>
      <VersionList {...props} />
    </details>
  );
}

/**
 * The same list as a floating control, for switching versions mid-text
 * without scrolling back to the header: a button that opens the list in a
 * popover. Shown while `visible` (the header's list is off screen) and kept
 * while its popover is open. Escape or a click outside closes it.
 * Placement (VersionSwitcher.module.css): in the left margin where the page
 * has one, else at the bottom right.
 */
export function FloatingVersions({ visible, ...props }: VersionsProps & { visible: boolean }) {
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const button = useRef<HTMLButtonElement>(null);
  const panel = useRef<HTMLDivElement>(null);
  const panelId = useId();
  const headingId = useId();

  // Opening moves focus into the list; Escape closes it and returns focus to
  // the button; a click outside closes it.
  useEffect(() => {
    if (!open) return;
    panel.current?.querySelector<HTMLElement>("a")?.focus();
    const outside = (e: PointerEvent) => {
      if (!root.current?.contains(e.target as Node)) setOpen(false);
    };
    const escape = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      setOpen(false);
      button.current?.focus();
    };
    document.addEventListener("pointerdown", outside);
    document.addEventListener("keydown", escape);
    return () => {
      document.removeEventListener("pointerdown", outside);
      document.removeEventListener("keydown", escape);
    };
  }, [open]);

  if (!visible && !open) return null;

  return (
    <div className={styles.floating} ref={root}>
      <button
        ref={button}
        type="button"
        className={styles.toggle}
        aria-expanded={open}
        aria-controls={panelId}
        onClick={() => setOpen((o) => !o)}
      >
        Other versions{" "}
        {/* Hidden on phones, where the button must stay small; below the label on wide screens. */}
        <span className={styles.count}>({versionsCount(props.current, props.members)})</span>
      </button>
      {open && (
        <div id={panelId} ref={panel} className={styles.panel} role="dialog" aria-labelledby={headingId}>
          <p id={headingId} className={styles.panelTitle}>
            Other versions
          </p>
          <VersionList {...props} />
        </div>
      )}
    </div>
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
  details: VersionDetails;
  original: boolean;
  label: string;
  showLanguage: boolean;
  positionFor?: PositionFor;
}

function VersionEntry({ work, details, original, label, showLanguage, positionFor }: EntryProps) {
  const id = useId();
  const lang = languageInfo(work.language);
  const facts: ReactNode[] = [];
  if (showLanguage) facts.push(lang.name);
  if (details.title) {
    facts.push(
      <span lang={lang.lang} dir="auto">
        {details.title}
      </span>,
    );
  }
  if (details.edition) facts.push(details.edition);

  return (
    <li className={styles.entry}>
      <VersionLink target={work} positionFor={positionFor} aria-describedby={facts.length ? id : undefined}>
        {label}
      </VersionLink>
      {original && <span className={styles.badge}>Original</span>}
      {facts.length > 0 && (
        <span id={id} className={styles.facts}>
          {facts.map((f, i) => (
            <span key={i}>
              {i > 0 && <span aria-hidden="true"> · </span>}
              {i > 0 && <span className="visually-hidden">, </span>}
              {f}
            </span>
          ))}
        </span>
      )}
    </li>
  );
}
