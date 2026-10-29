"use client";

import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import { useCallback, useMemo, useRef, type ReactNode } from "react";

import { formatDateLong, GENRES, LICENSES } from "@/lib/format";
import { languageInfo } from "@/lib/lang";
import {
  loadLibrary,
  loadWork,
  workAuthors,
  workHref,
  workIdFromSegments,
  type Library,
  type WorkRow,
} from "@/lib/library";
import { canReadInParallel, parallelHref, parallelIds } from "@/lib/parallel";
import { workTitle } from "@/lib/seo";
import { useLoaded } from "@/lib/useLoaded";
import { useOffscreen } from "@/lib/useOffscreen";
import { currentPosition, originalIds, positionIn, versionMembers } from "@/lib/versions";

import AuthorLinks from "./AuthorLinks";
import LoadError from "./LoadError";
import ParallelReader from "./ParallelReader";
import VersionSwitcher, { FloatingVersions, VersionLink, type PositionFor } from "./VersionSwitcher";
import WorkText from "./WorkText";
import styles from "./WorkReader.module.css";

/** `placeholder`: what the server renders while the library loads (components/Prerendered.tsx, #406). */
export default function WorkReader({ placeholder }: { placeholder?: ReactNode }) {
  const params = useParams<{ id: string[] }>();
  const id = workIdFromSegments(params.id ?? []);
  // `?with=` opens parallel reading (#181). The page wraps the reader in Suspense for this.
  const search = useSearchParams();
  const withIds = parallelIds(search, id);
  const library = useLoaded(loadLibrary);

  if (library.status === "loading") return placeholder ?? <p>Loading…</p>;
  if (library.status === "error") return <LoadError error={library.error} />;

  const row = library.data.index.works.find((w) => w.id === id);
  if (!row) {
    return (
      <div>
        <h1>Work not found</h1>
        <p>
          No work with the id <code>{id}</code> is in the library. <Link href="/works">Back to the library</Link>
        </p>
      </div>
    );
  }
  // Keyed by work (and versions) so navigating to another starts a fresh load.
  if (withIds.length > 0) {
    return <ParallelReader key={[row.id, ...withIds].join("\n")} lead={row} withIds={withIds} library={library.data} />;
  }
  return <Reader key={row.id} row={row} library={library.data} />;
}

function Reader({ row, library }: { row: WorkRow; library: Library }) {
  const { index, authors } = library;
  const work = useLoaded(() => loadWork(row.file));
  const lang = languageInfo(row.language);
  const collection = index.sources[row.source_id] ?? row.source_id;
  const license = LICENSES[row.license] ?? { label: row.license };
  const original = row.translation_of ? index.works.find((w) => w.id === row.translation_of) : undefined;
  const members = useMemo(() => versionMembers(index, row), [index, row]);
  const originals = useMemo(() => originalIds(members), [members]);
  // Without a translation_of link, name the group's originals instead (Scripture).
  const groupOriginals =
    row.translation_of || originals.has(row.id) ? [] : members.filter((w) => originals.has(w.id));

  // Open another version at the passage being read (lib/versions.ts).
  const textRef = useRef<HTMLDivElement>(null);
  const fromWork = work.status === "ready" ? work.data : null;
  const here = useCallback(() => currentPosition(textRef.current, window.location.hash), []);
  const positionFor = useCallback<PositionFor>(
    async (target) => (fromWork ? positionIn(index, row, fromWork, here(), target) : null),
    [fromWork, row, index, here],
  );
  // Read side by side (#181): the same position in this work, with the other version beside it.
  const parallelFor = useCallback(
    (target: WorkRow) => (canReadInParallel(index, row) ? parallelHref(row.id, [target.id]) : null),
    [index, row],
  );
  const versionProps = {
    current: row,
    members,
    originals,
    sources: index.sources,
    positionFor,
    parallelFor,
    here: async () => (fromWork ? here() : null),
  };
  const hasVersions = members.length > 1;
  const headerVersions = useRef<HTMLDetailsElement>(null);
  const headerVersionsOffscreen = useOffscreen(headerVersions);

  // Previous and next work in the same collection, in index order.
  const [prev, next] = useMemo(() => {
    const siblings = index.works.filter((w) => w.source_id === row.source_id);
    const i = siblings.findIndex((w) => w.id === row.id);
    return [siblings[i - 1], siblings[i + 1]];
  }, [index, row]);

  const byline = workAuthors(row, authors);
  const names = byline.map((a) => a.name).join(", ");
  // The source's own attribution, kept for provenance when it differs from the index's names.
  const attribution = row.author && row.author !== names ? row.author : null;
  const originalNames = original ? workAuthors(original, authors).map((a) => a.name).join(", ") : "";

  return (
    <article className={hasVersions ? styles.withVersions : undefined}>
      <title>{`${workTitle(row, authors, index)} · Patristica`}</title>
      <nav className={styles.crumbs} aria-label="Breadcrumb">
        <Link href="/works">Library</Link>
        <span aria-hidden="true"> / </span>
        <Link href={`/works?source=${encodeURIComponent(row.source_id)}`}>{collection}</Link>
      </nav>

      <header className={styles.header}>
        <h1 lang={lang.lang} dir="auto">
          {row.title}
        </h1>
        {byline.length > 0 && (
          <p
            className={styles.author}
            lang={byline.some((a) => a.id === null) ? lang.lang : undefined}
            dir="auto"
          >
            <AuthorLinks authors={byline} />
          </p>
        )}
        {/* At a glance: when, in what language, what kind. The rest folds away under Details. */}
        <dl className={styles.facts}>
          <div>
            <dt>Date</dt>
            <dd>{formatDateLong(row)}</dd>
          </div>
          <div>
            <dt>Language</dt>
            <dd>{lang.name}</dd>
          </div>
          <div>
            <dt>Genre</dt>
            <dd>{GENRES[row.genre] ?? row.genre}</dd>
          </div>
        </dl>
        <details className={styles.details}>
          <summary>Details</summary>
          <dl className={styles.meta}>
            {attribution && (
              <>
                <dt>Attributed as</dt>
                <dd lang={lang.lang} dir="auto">
                  {attribution}
                </dd>
              </>
            )}
            <dt>Collection</dt>
            <dd>{collection}</dd>
            {row.edition && (
              <>
                <dt>Edition</dt>
                <dd>{row.edition}</dd>
              </>
            )}
            <dt>Licence</dt>
            <dd>{license.url ? <a href={license.url}>{license.label}</a> : license.label}</dd>
            {row.provenance_url && (
              <>
                <dt>Source</dt>
                <dd className={styles.url}>
                  <a href={row.provenance_url}>{row.provenance_url}</a>
                </dd>
              </>
            )}
            {row.translation_of && (
              <>
                <dt>Translation of</dt>
                <dd>
                  {original ? (
                    <VersionLink target={original} positionFor={positionFor}>
                      {originalNames ? `${originalNames}, ` : ""}
                      {original.title}
                    </VersionLink>
                  ) : (
                    <code>{row.translation_of}</code>
                  )}
                </dd>
              </>
            )}
            {groupOriginals.length > 0 && (
              <>
                <dt>Original</dt>
                <dd>
                  {groupOriginals.map((w, i) => (
                    <span key={w.id}>
                      {i > 0 && ", "}
                      <VersionLink target={w} positionFor={positionFor}>
                        {languageInfo(w.language).name}: {index.sources[w.source_id] ?? w.source_id}
                      </VersionLink>
                    </span>
                  ))}
                </dd>
              </>
            )}
          </dl>
        </details>
        <VersionSwitcher ref={headerVersions} {...versionProps} />
      </header>

      {/* Once the header's list is off screen, the same list floats beside the text. */}
      {hasVersions && <FloatingVersions visible={headerVersionsOffscreen} {...versionProps} />}

      {work.status === "loading" && <p>Loading the text…</p>}
      {work.status === "error" && <LoadError error={work.error} />}
      <div ref={textRef}>
        {work.status === "ready" && (
          <WorkText work={work.data} genre={row.genre} language={row.language} sourceId={row.source_id} />
        )}
      </div>

      <nav className={styles.pager} aria-label="Other works in this collection">
        {prev ? (
          <Link href={workHref(prev.id)} rel="prev">
            ← {prev.title}
          </Link>
        ) : (
          <span />
        )}
        {next && (
          <Link href={workHref(next.id)} rel="next">
            {next.title} →
          </Link>
        )}
      </nav>
    </article>
  );
}
