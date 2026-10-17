"use client";

import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useMemo } from "react";

import {
  authorFacet,
  DEFAULT_VIEW,
  filterWorks,
  parseViewState,
  sortWorks,
  viewStateToParams,
  type SortKey,
  type ViewState,
} from "@/lib/filter";
import { formatDate, GENRES } from "@/lib/format";
import { languageInfo } from "@/lib/lang";
import { loadLibrary, workAuthors, workHref, type Library } from "@/lib/library";
import { useLoaded } from "@/lib/useLoaded";

import AuthorLinks from "./AuthorLinks";
import LoadError from "./LoadError";
import styles from "./LibraryBrowser.module.css";

const COLUMNS: { key: SortKey; label: string; numeric?: boolean }[] = [
  { key: "author", label: "Author" },
  { key: "title", label: "Title" },
  { key: "language", label: "Language" },
  { key: "date", label: "Date", numeric: true },
  { key: "source", label: "Collection" },
  { key: "chunks", label: "Chunks", numeric: true },
];

export default function LibraryBrowser() {
  const library = useLoaded(loadLibrary);
  if (library.status === "loading") return <p>Loading the library…</p>;
  if (library.status === "error") return <LoadError error={library.error} />;
  return <Browser library={library.data} />;
}

function Browser({ library }: { library: Library }) {
  const { index, authors } = library;
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const view = useMemo(() => parseViewState(new URLSearchParams(params.toString())), [params]);

  const update = (changes: Partial<ViewState>) => {
    const query = viewStateToParams({ ...view, ...changes }).toString();
    router.replace(query ? `${pathname}?${query}` : pathname, { scroll: false });
  };

  const rows = useMemo(
    () =>
      sortWorks(
        filterWorks(index.works, view, index.sources, authors),
        view.sort,
        view.dir,
        index.sources,
        authors,
      ),
    [index, authors, view],
  );

  const facets = useMemo(() => {
    const present = (key: "language" | "genre") => [...new Set(index.works.map((w) => w[key]))];
    return {
      languages: present("language").sort((a, b) =>
        languageInfo(a).name.localeCompare(languageInfo(b).name),
      ),
      genres: present("genre").sort(),
      sources: Object.entries(index.sources).sort((a, b) => a[1].localeCompare(b[1])),
      authors: authorFacet(index.works, authors),
    };
  }, [index, authors]);

  const sortBy = (key: SortKey) =>
    update({ sort: key, dir: view.sort === key && view.dir === "asc" ? "desc" : "asc" });

  const isFiltered = viewStateToParams({ ...view, sort: DEFAULT_VIEW.sort, dir: DEFAULT_VIEW.dir })
    .toString() !== "";

  return (
    <div>
      <form className={styles.filters} role="search" onSubmit={(e) => e.preventDefault()}>
        <label className={styles.query}>
          <span>Search authors and titles</span>
          <input
            type="search"
            value={view.q}
            placeholder="e.g. Augustine, Hieronymus, homily, Ἰωάννης"
            onChange={(e) => update({ q: e.target.value })}
          />
        </label>
        <label>
          <span>Author</span>
          <select value={view.author} onChange={(e) => update({ author: e.target.value })}>
            <option value="">All</option>
            {facets.authors.map((a) => (
              <option key={a.id} value={a.id}>
                {a.name} ({a.count.toLocaleString()})
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>Language</span>
          <select value={view.language} onChange={(e) => update({ language: e.target.value })}>
            <option value="">All</option>
            {facets.languages.map((code) => (
              <option key={code} value={code}>
                {languageInfo(code).name}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>Genre</span>
          <select value={view.genre} onChange={(e) => update({ genre: e.target.value })}>
            <option value="">All</option>
            {facets.genres.map((g) => (
              <option key={g} value={g}>
                {GENRES[g] ?? g}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>Collection</span>
          <select value={view.source} onChange={(e) => update({ source: e.target.value })}>
            <option value="">All</option>
            {facets.sources.map(([id, label]) => (
              <option key={id} value={id}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <fieldset className={styles.years}>
          <legend>Date (negative = BC)</legend>
          <input
            type="number"
            inputMode="numeric"
            aria-label="From year"
            placeholder="From"
            value={view.from ?? ""}
            onChange={(e) => update({ from: e.target.value === "" ? null : Number(e.target.value) })}
          />
          <span aria-hidden="true">–</span>
          <input
            type="number"
            inputMode="numeric"
            aria-label="To year"
            placeholder="To"
            value={view.to ?? ""}
            onChange={(e) => update({ to: e.target.value === "" ? null : Number(e.target.value) })}
          />
        </fieldset>
      </form>

      <p className={styles.count} aria-live="polite">
        {rows.length === index.works.length
          ? `${rows.length.toLocaleString()} works`
          : `${rows.length.toLocaleString()} of ${index.works.length.toLocaleString()} works`}
        {isFiltered && (
          <>
            {" · "}
            <button type="button" className={styles.reset} onClick={() => update(DEFAULT_VIEW)}>
              Clear filters
            </button>
          </>
        )}
      </p>

      <div className={styles.tableWrap}>
        <table className={styles.table}>
          <thead>
            <tr>
              {COLUMNS.map((col) => (
                <th
                  key={col.key}
                  className={col.numeric ? styles.numeric : undefined}
                  aria-sort={
                    view.sort === col.key ? (view.dir === "asc" ? "ascending" : "descending") : "none"
                  }
                >
                  <button type="button" onClick={() => sortBy(col.key)}>
                    {col.label}
                    <span className={styles.arrow} aria-hidden="true">
                      {view.sort === col.key ? (view.dir === "asc" ? "▲" : "▼") : ""}
                    </span>
                  </button>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((w) => {
              const lang = languageInfo(w.language);
              const byline = workAuthors(w, authors);
              // Names from the author index are English; a fallback is the source's own string.
              const sourceString = byline.some((a) => a.id === null);
              return (
                <tr key={w.id}>
                  <td lang={sourceString ? lang.lang : undefined} dir="auto">
                    {byline.length > 0 ? (
                      <AuthorLinks authors={byline} />
                    ) : (
                      <span className={styles.muted}>Anonymous</span>
                    )}
                  </td>
                  <td lang={lang.lang} dir="auto">
                    <Link href={workHref(w.id)}>
                      {w.title}
                    </Link>
                  </td>
                  <td>{lang.name}</td>
                  <td className={styles.numeric}>{formatDate(w)}</td>
                  <td>{index.sources[w.source_id] ?? w.source_id}</td>
                  <td className={styles.numeric}>{w.chunks.toLocaleString()}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
