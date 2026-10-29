// Server-rendered stand-ins for the client pages (#406). The reader, the
// library and the author pages load the library in the browser; until they
// have, they show these (their `placeholder` prop) instead of "Loading…", so
// the server's HTML has the same title, authors, versions and work lists, as
// plain links that crawlers can follow.

import Link from "next/link";
import { Fragment } from "react";

import { formatAuthorDate, formatDate, formatDateLong, formatLifespan, GENRES } from "@/lib/format";
import { languageInfo } from "@/lib/lang";
import { authorHref, workAuthors, workHref, type Author, type Library, type WorkRow } from "@/lib/library";

import AuthorLinks from "./AuthorLinks";
import authorStyles from "./AuthorPage.module.css";
import readerStyles from "./WorkReader.module.css";

/** A schema.org JSON-LD block (lib/seo.ts). */
export function JsonLd({ data }: { data: Record<string, unknown> }) {
  return (
    <script
      type="application/ld+json"
      // `<` is escaped so the text can't close the script element.
      dangerouslySetInnerHTML={{ __html: JSON.stringify(data).replace(/</g, "\\u003c") }}
    />
  );
}

/** A list of works, each linked to the reader, with its collection and date. */
function WorkLinks({ works, library }: { works: readonly WorkRow[]; library: Library }) {
  return (
    <ul className={authorStyles.works}>
      {works.map((w) => (
        <li key={w.id}>
          <Link href={workHref(w.id)} lang={languageInfo(w.language).lang} dir="auto">
            {w.title}
          </Link>
          <span className={authorStyles.muted}>
            {" · "}
            {[library.index.sources[w.source_id] ?? w.source_id, formatDate(w)].filter(Boolean).join(" · ")}
          </span>
        </li>
      ))}
    </ul>
  );
}

/** Works grouped by language, most works first. */
function byLanguage(works: readonly WorkRow[]): [string, WorkRow[]][] {
  const groups = new Map<string, WorkRow[]>();
  for (const w of works) groups.set(w.language, [...(groups.get(w.language) ?? []), w]);
  return [...groups].sort(([, a], [, b]) => b.length - a.length);
}

/** The reader's header, versions and pager, while the reader loads. */
export function WorkSummary({ row, library }: { row: WorkRow; library: Library }) {
  const { index, authors } = library;
  const lang = languageInfo(row.language);
  const collection = index.sources[row.source_id] ?? row.source_id;
  const byline = workAuthors(row, authors);
  const versions = row.version_group
    ? index.works.filter((w) => w.version_group === row.version_group && w.id !== row.id)
    : [];
  const siblings = index.works.filter((w) => w.source_id === row.source_id);
  const i = siblings.indexOf(row);
  const [prev, next] = [siblings[i - 1], siblings[i + 1]];
  return (
    <article>
      <nav className={readerStyles.crumbs} aria-label="Breadcrumb">
        <Link href="/works">Library</Link>
        <span aria-hidden="true"> / </span>
        {collection}
      </nav>
      <header className={readerStyles.header}>
        <h1 lang={lang.lang} dir="auto">
          {row.title}
        </h1>
        {byline.length > 0 && (
          <p className={readerStyles.author} dir="auto">
            <AuthorLinks authors={byline} />
          </p>
        )}
        <dl className={readerStyles.facts}>
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
        {versions.length > 0 && (
          <nav aria-label="Other versions">
            <p>Other versions:</p>
            <ul className={authorStyles.works}>
              {versions.map((w) => (
                <li key={w.id}>
                  <Link href={workHref(w.id)}>
                    {languageInfo(w.language).name}: {index.sources[w.source_id] ?? w.source_id}
                  </Link>
                </li>
              ))}
            </ul>
          </nav>
        )}
      </header>
      <p>Loading the text…</p>
      <nav className={readerStyles.pager} aria-label="Other works in this collection">
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

/** The author page's header and work list, while the page loads. */
export function AuthorSummary({ author, works, library }: { author: Author; works: WorkRow[]; library: Library }) {
  const dates: [string, string][] = [
    ["Born", author.birth ? formatAuthorDate(author.birth) : ""],
    ["Died", author.death ? formatAuthorDate(author.death) : ""],
    ["Active", author.floruit ? `fl. ${formatAuthorDate(author.floruit)}` : ""],
  ];
  return (
    <article>
      <nav className={authorStyles.crumbs} aria-label="Breadcrumb">
        <Link href="/works">Library</Link>
        <span aria-hidden="true"> / </span>
        <Link href="/authors">Authors</Link>
      </nav>
      <header className={authorStyles.header}>
        <h1>{author.name}</h1>
        <dl className={authorStyles.meta}>
          {dates
            .filter(([, value]) => value)
            .map(([label, value]) => (
              <Fragment key={label}>
                <dt>{label}</dt>
                <dd>{value}</dd>
              </Fragment>
            ))}
          {author.aliases.length > 0 && (
            <>
              <dt>Also known as</dt>
              <dd dir="auto">{author.aliases.join(" · ")}</dd>
            </>
          )}
        </dl>
      </header>
      <section aria-labelledby="works">
        <h2 id="works" className={authorStyles.worksTitle}>
          {works.length.toLocaleString("en")} {works.length === 1 ? "work" : "works"}
        </h2>
        {byLanguage(works).map(([language, group]) => (
          <section key={language} className={authorStyles.group} aria-label={languageInfo(language).name}>
            <h3>{languageInfo(language).name}</h3>
            <WorkLinks works={group} library={library} />
          </section>
        ))}
      </section>
    </article>
  );
}

/** Every work of the library, by collection, while the library browser loads: titles and authors only (~4k rows). */
export function WorkListing({ library }: { library: Library }) {
  const { index, authors } = library;
  const bySource = new Map<string, WorkRow[]>();
  for (const w of index.works) bySource.set(w.source_id, [...(bySource.get(w.source_id) ?? []), w]);
  return (
    <div>
      <p>Loading the library…</p>
      {[...bySource].map(([source, works]) => (
        <section key={source} className={authorStyles.group}>
          <h2>{index.sources[source] ?? source}</h2>
          <ul className={authorStyles.works}>
            {works.map((w) => {
              const names = workAuthors(w, authors).map((a) => a.name);
              return (
                <li key={w.id}>
                  <Link href={workHref(w.id)} lang={languageInfo(w.language).lang} dir="auto">
                    {w.title}
                  </Link>
                  {names.length > 0 && ` · ${names.join(", ")}`}
                </li>
              );
            })}
          </ul>
        </section>
      ))}
    </div>
  );
}

/** Every author with works, while the author list loads. */
export function AuthorListing({ library }: { library: Library }) {
  const counts = new Map<string, number>();
  for (const w of library.index.works) {
    for (const id of new Set(w.author_ids)) counts.set(id, (counts.get(id) ?? 0) + 1);
  }
  const shown = [...library.authors.values()]
    .filter((a) => counts.has(a.id))
    .sort((a, b) => a.name.localeCompare(b.name, "en"));
  return (
    <div>
      <p>Loading…</p>
      <ul className={authorStyles.works}>
        {shown.map((a) => {
          const lifespan = formatLifespan(a);
          const n = counts.get(a.id) ?? 0;
          return (
            <li key={a.id}>
              <Link href={authorHref(a.id)}>{a.name}</Link>
              <span className={authorStyles.muted}>
                {" · "}
                {[lifespan, `${n.toLocaleString("en")} ${n === 1 ? "work" : "works"}`].filter(Boolean).join(" · ")}
              </span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
