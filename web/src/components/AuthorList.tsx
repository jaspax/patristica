"use client";

import Link from "next/link";
import { useMemo, useState } from "react";

import { filterAuthors } from "@/lib/authors";
import { workCounts } from "@/lib/filter";
import { formatLifespan, TRADITIONS } from "@/lib/format";
import { authorHref, loadLibrary, type Library } from "@/lib/library";
import { useLoaded } from "@/lib/useLoaded";

import LoadError from "./LoadError";
import styles from "./AuthorList.module.css";

export default function AuthorList() {
  const library = useLoaded(loadLibrary);
  if (library.status === "loading") return <p>Loading…</p>;
  if (library.status === "error") return <LoadError error={library.error} />;
  return <List library={library.data} />;
}

function List({ library }: { library: Library }) {
  const [query, setQuery] = useState("");
  const counts = useMemo(() => workCounts(library.index.works), [library]);
  const all = useMemo(() => filterAuthors(library.authors, counts, ""), [library, counts]);
  const shown = useMemo(
    () => (query ? filterAuthors(library.authors, counts, query) : all),
    [library, counts, query, all],
  );

  return (
    <div>
      <form className={styles.filters} role="search" onSubmit={(e) => e.preventDefault()}>
        <label>
          <span>Find an author (names in any language)</span>
          <input
            type="search"
            value={query}
            placeholder="e.g. Chrysostom, Hieronymus"
            onChange={(e) => setQuery(e.target.value)}
          />
        </label>
      </form>
      <p className={styles.count} aria-live="polite">
        {shown.length === all.length
          ? `${all.length.toLocaleString()} authors`
          : `${shown.length.toLocaleString()} of ${all.length.toLocaleString()} authors`}
      </p>
      <div className={styles.wrap}>
        <table className={styles.table}>
          <thead>
            <tr>
              <th>Author</th>
              <th>Dates</th>
              <th>Tradition</th>
              <th className={styles.numeric}>Works</th>
            </tr>
          </thead>
          <tbody>
            {shown.map((a) => (
              <tr key={a.id}>
                <td>
                  <Link href={authorHref(a.id)}>{a.name}</Link>
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
