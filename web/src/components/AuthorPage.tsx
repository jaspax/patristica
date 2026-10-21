"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useMemo } from "react";

import { pseudonymsOf, worksByLanguage } from "@/lib/authors";
import { authorFilterHref, workCounts } from "@/lib/filter";
import { formatAuthorDate, formatDate, TRADITIONS } from "@/lib/format";
import { languageInfo } from "@/lib/lang";
import { authorHref, loadLibrary, workHref, type Author, type Library } from "@/lib/library";
import { useLoaded } from "@/lib/useLoaded";

import LoadError from "./LoadError";
import styles from "./AuthorPage.module.css";

export default function AuthorPage() {
  const params = useParams<{ id: string }>();
  const id = decodeURIComponent(params.id ?? "");
  const library = useLoaded(loadLibrary);

  if (library.status === "loading") return <p>Loading…</p>;
  if (library.status === "error") return <LoadError error={library.error} />;

  const author = library.data.authors.get(id);
  if (!author) {
    return (
      <div>
        <h1>Author not found</h1>
        <p>
          No author with the id <code>{id}</code> is in the author index.{" "}
          <Link href="/authors">All authors</Link>
        </p>
      </div>
    );
  }
  return <Profile author={author} library={library.data} />;
}

function AuthorLink({ author, count }: { author: Author; count?: number }) {
  return (
    <>
      <Link href={authorHref(author.id)}>{author.name}</Link>
      {count !== undefined && (
        <span className={styles.muted}>
          {" "}
          ({count.toLocaleString()} {count === 1 ? "work" : "works"})
        </span>
      )}
    </>
  );
}

function Profile({ author, library }: { author: Author; library: Library }) {
  const { index, authors } = library;
  const groups = useMemo(() => worksByLanguage(index.works, author.id), [index, author]);
  const counts = useMemo(() => workCounts(index.works), [index]);
  const pseudonyms = useMemo(() => pseudonymsOf(authors, author.id), [authors, author]);
  const real = author.pseudo_of ? authors.get(author.pseudo_of) : undefined;
  const total = counts.get(author.id) ?? 0;

  return (
    <article>
      <title>{`${author.name} · Patristica`}</title>
      <nav className={styles.crumbs} aria-label="Breadcrumb">
        <Link href="/works">Library</Link>
        <span aria-hidden="true"> / </span>
        <Link href="/authors">Authors</Link>
      </nav>

      <header className={styles.header}>
        <h1>{author.name}</h1>
        <dl className={styles.meta}>
          {author.birth && (
            <>
              <dt>Born</dt>
              <dd>{formatAuthorDate(author.birth)}</dd>
            </>
          )}
          {author.death && (
            <>
              <dt>Died</dt>
              <dd>{formatAuthorDate(author.death)}</dd>
            </>
          )}
          {author.floruit && (
            <>
              <dt>Active</dt>
              <dd>fl. {formatAuthorDate(author.floruit)}</dd>
            </>
          )}
          {author.tradition && (
            <>
              <dt>Tradition</dt>
              <dd>{TRADITIONS[author.tradition] ?? author.tradition}</dd>
            </>
          )}
          {real && (
            <>
              <dt>Pseudonymous</dt>
              <dd>
                Works that carry the name of{" "}
                <AuthorLink author={real} count={counts.get(real.id) ?? 0} />
              </dd>
            </>
          )}
          {pseudonyms.length > 0 && (
            <>
              <dt>Pseudonymous works</dt>
              <dd>
                <ul className={styles.inlineList}>
                  {pseudonyms.map((p) => (
                    <li key={p.id}>
                      <AuthorLink author={p} count={counts.get(p.id) ?? 0} />
                    </li>
                  ))}
                </ul>
              </dd>
            </>
          )}
          {author.aliases.length > 0 && (
            <>
              <dt>Also known as</dt>
              <dd dir="auto">{author.aliases.join(" · ")}</dd>
            </>
          )}
          {author.external_ids.length > 0 && (
            <>
              <dt>Catalogue ids</dt>
              <dd>{author.external_ids.join(", ")}</dd>
            </>
          )}
        </dl>
        {author.birth || author.death || author.floruit ? null : (
          <p className={styles.note}>No dates are recorded for this author.</p>
        )}
      </header>

      <section aria-labelledby="works">
        <h2 id="works" className={styles.worksTitle}>
          {total === 0 ? "No works in the library" : `${total.toLocaleString()} ${total === 1 ? "work" : "works"}`}
          {total > 0 && (
            <Link className={styles.browse} href={authorFilterHref(author.id)}>
              Filter the library to these works
            </Link>
          )}
        </h2>
        {groups.map((group) => {
          const lang = languageInfo(group.language);
          return (
            <section key={group.language} className={styles.group} aria-label={lang.name}>
              <h3>
                {lang.name} <span className={styles.muted}>({group.works.length.toLocaleString()})</span>
              </h3>
              <ul className={styles.works}>
                {group.works.map((w) => (
                  <li key={w.id}>
                    <Link href={workHref(w.id)} lang={lang.lang} dir="auto">
                      {w.title}
                    </Link>
                    <span className={styles.muted}>
                      {" · "}
                      {[index.sources[w.source_id] ?? w.source_id, formatDate(w)].filter(Boolean).join(" · ")}
                    </span>
                  </li>
                ))}
              </ul>
            </section>
          );
        })}
      </section>
    </article>
  );
}
