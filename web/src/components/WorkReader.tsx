"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useMemo } from "react";

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
import { useLoaded } from "@/lib/useLoaded";

import AuthorLinks from "./AuthorLinks";
import LoadError from "./LoadError";
import WorkText from "./WorkText";
import styles from "./WorkReader.module.css";

export default function WorkReader() {
  const params = useParams<{ id: string[] }>();
  const id = workIdFromSegments(params.id ?? []);
  const library = useLoaded(loadLibrary);

  if (library.status === "loading") return <p>Loading…</p>;
  if (library.status === "error") return <LoadError error={library.error} />;

  const row = library.data.index.works.find((w) => w.id === id);
  if (!row) {
    return (
      <div>
        <h1>Work not found</h1>
        <p>
          No work with the id <code>{id}</code> is in the library. <Link href="/">Back to the library</Link>
        </p>
      </div>
    );
  }
  // Keyed by work so navigating to another work starts a fresh load.
  return <Reader key={row.id} row={row} library={library.data} />;
}

function Reader({ row, library }: { row: WorkRow; library: Library }) {
  const { index, authors } = library;
  const work = useLoaded(() => loadWork(row.file));
  const lang = languageInfo(row.language);
  const collection = index.sources[row.source_id] ?? row.source_id;
  const license = LICENSES[row.license] ?? { label: row.license };
  const original = row.translation_of ? index.works.find((w) => w.id === row.translation_of) : undefined;

  // Previous and next work in the same collection, in index order.
  const [prev, next] = useMemo(() => {
    const siblings = index.works.filter((w) => w.source_id === row.source_id);
    const i = siblings.findIndex((w) => w.id === row.id);
    return [siblings[i - 1], siblings[i + 1]];
  }, [index, row]);

  const byline = workAuthors(row, authors);
  const names = byline.map((a) => a.name).join(", ");
  const citation = names ? `${names}, ${row.title}` : row.title;
  // The source's own attribution, kept for provenance when it differs from the index's names.
  const attribution = row.author && row.author !== names ? row.author : null;
  const originalNames = original ? workAuthors(original, authors).map((a) => a.name).join(", ") : "";

  return (
    <article>
      <title>{`${citation} · Patristica`}</title>
      <nav className={styles.crumbs} aria-label="Breadcrumb">
        <Link href="/">Library</Link>
        <span aria-hidden="true"> / </span>
        <Link href={`/?source=${encodeURIComponent(row.source_id)}`}>{collection}</Link>
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
        <dl className={styles.meta}>
          {attribution && (
            <>
              <dt>Attributed as</dt>
              <dd lang={lang.lang} dir="auto">
                {attribution}
              </dd>
            </>
          )}
          <dt>Date</dt>
          <dd>{formatDateLong(row)}</dd>
          <dt>Language</dt>
          <dd>{lang.name}</dd>
          <dt>Genre</dt>
          <dd>{GENRES[row.genre] ?? row.genre}</dd>
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
                  <Link href={workHref(original.id)}>
                    {originalNames ? `${originalNames}, ` : ""}
                    {original.title}
                  </Link>
                ) : (
                  <code>{row.translation_of}</code>
                )}
              </dd>
            </>
          )}
        </dl>
      </header>

      {work.status === "loading" && <p>Loading the text…</p>}
      {work.status === "error" && <LoadError error={work.error} />}
      {work.status === "ready" && <WorkText work={work.data} genre={row.genre} language={row.language} sourceId={row.source_id} />}

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
