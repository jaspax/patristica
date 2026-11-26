"use client";

import Link from "next/link";
import { useParams, usePathname, useRouter, useSearchParams } from "next/navigation";
import { useDeferredValue, useMemo, type ReactNode } from "react";

import { authorFacets, authorWorks, pseudonymsOf, worksByLanguage } from "@/lib/authors";
import {
  DEFAULT_VIEW,
  filterWorks,
  parseViewState,
  viewStateToParams,
  workCounts,
  type ViewState,
} from "@/lib/filter";
import { formatAuthorDate, formatDate, TRADITIONS } from "@/lib/format";
import { languageInfo } from "@/lib/lang";
import {
  authorAboutFile,
  authorHref,
  loadLibrary,
  workHref,
  type Author,
  type Library,
} from "@/lib/library";
import { useDebouncedText } from "@/lib/useDebouncedText";
import { useLoaded } from "@/lib/useLoaded";

import AboutPanel from "./AboutPanel";
import FilterFields from "./FilterFields";
import filterStyles from "./Filters.module.css";
import LoadError from "./LoadError";
import styles from "./AuthorPage.module.css";

/** `placeholder`: what the server renders while the library loads (components/Prerendered.tsx, #406). */
export default function AuthorPage({ placeholder }: { placeholder?: ReactNode }) {
  const params = useParams<{ id: string }>();
  const id = decodeURIComponent(params.id ?? "");
  const library = useLoaded(loadLibrary);

  if (library.status === "loading") return placeholder ?? <p>Loading…</p>;
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
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  // The library's filters (and URL parameters), less the author facet: this page is one author's.
  const view = useMemo(
    () => ({ ...parseViewState(new URLSearchParams(params.toString())), author: [] }),
    [params],
  );
  const writeUrl = (next: ViewState) => {
    const params = viewStateToParams({ ...next, author: [] }).toString();
    router.replace(params ? `${pathname}?${params}` : pathname, { scroll: false });
  };
  // The input shows each keystroke at once; the URL and the list follow (#497).
  const query = useDebouncedText(view.q, (q) => writeUrl({ ...view, q }));
  const q = useDeferredValue(query.text);
  const update = (changes: Partial<ViewState>) => {
    const next = { ...view, q: query.text, ...changes };
    query.setNow(next.q);
    writeUrl(next);
  };

  const own = useMemo(() => authorWorks(index.works, author.id), [index, author]);
  const facets = useMemo(() => authorFacets(index, own, authors), [index, own, authors]);
  const shown = useMemo(
    () => filterWorks(own, { ...view, q }, index.sources, authors),
    [own, view, q, index, authors],
  );
  const groups = useMemo(() => worksByLanguage(shown, author.id), [shown, author]);
  const counts = useMemo(() => workCounts(index.works), [index]);
  const pseudonyms = useMemo(() => pseudonymsOf(authors, author.id), [authors, author]);
  const real = author.pseudo_of ? authors.get(author.pseudo_of) : undefined;
  const total = own.length;
  const isFiltered = viewStateToParams({ ...view, q: query.text, sort: DEFAULT_VIEW.sort, dir: DEFAULT_VIEW.dir }).toString() !== "";
  // The same filters in the library, with this author selected.
  const libraryHref = `/works?${viewStateToParams({ ...view, q: query.text, author: [author.id] })}`;

  return (
    <article>
      <title>{`${author.name} · Patristica`}</title>
      <nav className={styles.crumbs} aria-label="Breadcrumb">
        <Link href="/works">Library</Link>
        <span aria-hidden="true"> / </span>
        <Link href="/authors">Authors</Link>
      </nav>

      <header className={author.about ? `${styles.header} ${styles.withAbout}` : styles.header}>
        <div className={styles.headMain}>
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
        </div>
        {/* The author's bio (#795), to the right of the facts. */}
        {author.about && <AboutPanel file={authorAboutFile(author.id)} label={`About ${author.name}`} />}
      </header>

      <section aria-labelledby="works">
        <h2 id="works" className={styles.worksTitle}>
          {total === 0 ? "No works in the library" : `${total.toLocaleString()} ${total === 1 ? "work" : "works"}`}
          {total > 0 && (
            <Link className={styles.browse} href={libraryHref}>
              Filter the library to these works
            </Link>
          )}
        </h2>
        {total > 1 && (
          <form
            className={`${filterStyles.filters} ${styles.filters}`}
            role="search"
            aria-label={`Filter ${author.name}'s works`}
            onSubmit={(e) => e.preventDefault()}
          >
            <label className={filterStyles.query}>
              <span>Search titles</span>
              <input
                type="search"
                value={query.text}
                placeholder="e.g. homily, De sacerdotio"
                onChange={(e) => query.setText(e.target.value)}
              />
            </label>
            <FilterFields value={view} facets={facets} onChange={update} withAuthor={false} />
          </form>
        )}
        {isFiltered && (
          <p className={styles.count} aria-live="polite">
            {shown.length.toLocaleString()} of {total.toLocaleString()} {total === 1 ? "work" : "works"}
            {" · "}
            <button type="button" className={styles.reset} onClick={() => update(DEFAULT_VIEW)}>
              Clear filters
            </button>
          </p>
        )}
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
