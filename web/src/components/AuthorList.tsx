"use client";

import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useDeferredValue, useMemo, type ReactNode } from "react";

import { filterAuthors } from "@/lib/authors";
import {
  DEFAULT_VIEW,
  filterWorks,
  libraryFacets,
  parseViewState,
  viewStateToParams,
  workCounts,
  type ViewState,
} from "@/lib/filter";
import { formatLifespan, TRADITIONS } from "@/lib/format";
import { authorHref, loadLibrary, type Library } from "@/lib/library";
import { useDebouncedText } from "@/lib/useDebouncedText";
import { useLoaded } from "@/lib/useLoaded";

import FilterFields from "./FilterFields";
import filterStyles from "./Filters.module.css";
import LoadError from "./LoadError";
import styles from "./AuthorList.module.css";

/** `placeholder`: what the server renders while the library loads (components/Prerendered.tsx, #406). */
export default function AuthorList({ placeholder }: { placeholder?: ReactNode }) {
  const library = useLoaded(loadLibrary);
  if (library.status === "loading") return placeholder ?? <p>Loading…</p>;
  if (library.status === "error") return <LoadError error={library.error} />;
  return <List library={library.data} />;
}

/** The view state's work facets: everything but the name query (and the author facet). */
function workFilters(view: ViewState): ViewState {
  return { ...view, q: "", author: [], sort: DEFAULT_VIEW.sort, dir: DEFAULT_VIEW.dir };
}

function List({ library }: { library: Library }) {
  const { index, authors } = library;
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  // The library's URL parameters: q searches names, the facets filter the works (#205).
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

  const facets = useMemo(() => libraryFacets(index, authors), [index, authors]);
  const allCounts = useMemo(() => workCounts(index.works), [index]);
  const all = useMemo(() => filterAuthors(authors, allCounts, ""), [authors, allCounts]);
  // An author is listed with the works the facets leave; one with none of them is not.
  const facetQuery = viewStateToParams(workFilters(view)).toString();
  const counts = useMemo(
    () => (facetQuery ? workCounts(filterWorks(index.works, workFilters(view), index.sources, authors)) : allCounts),
    [index, authors, allCounts, facetQuery, view],
  );
  const shown = useMemo(() => filterAuthors(authors, counts, q), [authors, counts, q]);
  const isFiltered = viewStateToParams({ ...view, q: query.text, sort: DEFAULT_VIEW.sort, dir: DEFAULT_VIEW.dir }).toString() !== "";

  return (
    <div>
      <form className={filterStyles.filters} role="search" onSubmit={(e) => e.preventDefault()}>
        <label className={filterStyles.query}>
          <span>Find an author (names in any language)</span>
          <input
            type="search"
            value={query.text}
            placeholder="e.g. Chrysostom, Hieronymus"
            onChange={(e) => query.setText(e.target.value)}
          />
        </label>
        <FilterFields value={view} facets={facets} onChange={update} withAuthor={false} />
      </form>
      <p className={styles.count} aria-live="polite">
        {shown.length === all.length
          ? `${all.length.toLocaleString()} authors`
          : `${shown.length.toLocaleString()} of ${all.length.toLocaleString()} authors`}
        {facetQuery && " with matching works"}
        {isFiltered && (
          <>
            {" · "}
            <button type="button" className={styles.reset} onClick={() => update(DEFAULT_VIEW)}>
              Clear filters
            </button>
          </>
        )}
      </p>
      <div className={styles.wrap}>
        <table className={styles.table}>
          <thead>
            <tr>
              <th>Author</th>
              <th>Dates</th>
              <th>Tradition</th>
              <th className={styles.numeric}>{facetQuery ? "Matching works" : "Works"}</th>
            </tr>
          </thead>
          <tbody>
            {shown.map((a) => (
              <tr key={a.id}>
                <td>
                  {/* The author's page opens with the same facets set. */}
                  <Link href={facetQuery ? `${authorHref(a.id)}?${facetQuery}` : authorHref(a.id)}>{a.name}</Link>
                </td>
                <td>{formatLifespan(a)}</td>
                <td>{a.tradition ? (TRADITIONS[a.tradition] ?? a.tradition) : ""}</td>
                <td className={styles.numeric}>{(counts.get(a.id) ?? 0).toLocaleString()}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
