"use client";

import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useMemo, type ReactNode } from "react";

import {
  DEFAULT_VIEW,
  filterWorks,
  libraryFacets,
  parseViewState,
  sortWorks,
  viewStateToParams,
  type SortKey,
  type ViewState,
} from "@/lib/filter";
import { formatDate } from "@/lib/format";
import { languageInfo } from "@/lib/lang";
import { loadLibrary, workAuthors, workHref, type Library } from "@/lib/library";
import { useLoaded } from "@/lib/useLoaded";
import { versionCounts } from "@/lib/versions";

import AuthorLinks from "./AuthorLinks";
import FilterFields from "./FilterFields";
import filterStyles from "./Filters.module.css";
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

/** `placeholder`: what the server renders while the library loads (components/Prerendered.tsx, #406). */
export default function LibraryBrowser({ placeholder }: { placeholder?: ReactNode }) {
  const library = useLoaded(loadLibrary);
  if (library.status === "loading") return placeholder ?? <p>Loading the library…</p>;
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

  const facets = useMemo(() => libraryFacets(index, authors), [index, authors]);
  const versions = useMemo(() => versionCounts(index.works), [index]);

  const sortBy = (key: SortKey) =>
    update({ sort: key, dir: view.sort === key && view.dir === "asc" ? "desc" : "asc" });

  const isFiltered = viewStateToParams({ ...view, sort: DEFAULT_VIEW.sort, dir: DEFAULT_VIEW.dir })
    .toString() !== "";

  return (
    <div>
      <form className={filterStyles.filters} role="search" onSubmit={(e) => e.preventDefault()}>
        <label className={filterStyles.query}>
          <span>Search authors and titles</span>
          <input
            type="search"
            value={view.q}
            placeholder="e.g. Augustine, Hieronymus, homily, Ἰωάννης"
            onChange={(e) => update({ q: e.target.value })}
          />
        </label>
        <FilterFields value={view} facets={facets} onChange={update} />
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
              const nVersions = w.version_group ? (versions.get(w.version_group) ?? 0) : 0;
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
                    {nVersions > 1 && (
                      <span className={styles.versions} lang="en" dir="ltr">
                        {nVersions} versions
                      </span>
                    )}
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
