"use client";

import Link from "next/link";
import { useMemo } from "react";

import { LICENSES } from "@/lib/format";
import { loadIndex, type LibraryIndex } from "@/lib/library";
import { summarizeSources } from "@/lib/sources";
import { useLoaded } from "@/lib/useLoaded";

import LoadError from "./LoadError";
import styles from "./SourcesTable.module.css";

export default function SourcesTable() {
  const index = useLoaded(loadIndex);
  if (index.status === "loading") return <p>Loading…</p>;
  if (index.status === "error") return <LoadError error={index.error} />;
  return <Table index={index.data} />;
}

function License({ id }: { id: string }) {
  const info = LICENSES[id] ?? { label: id };
  return info.url ? <a href={info.url}>{info.label}</a> : <>{info.label}</>;
}

function Table({ index }: { index: LibraryIndex }) {
  const sources = useMemo(() => summarizeSources(index), [index]);
  return (
    <div className={styles.wrap}>
      <table className={styles.table}>
        <thead>
          <tr>
            <th>Collection</th>
            <th className={styles.numeric}>Works</th>
            <th>Licence</th>
            <th>Edition and source</th>
          </tr>
        </thead>
        <tbody>
          {sources.map((s) => (
            <tr key={s.sourceId}>
              <td>
                <Link href={`/works?source=${encodeURIComponent(s.sourceId)}`}>{s.label}</Link>
                {s.nonCommercial && <span className={styles.nc}>non-commercial</span>}
              </td>
              <td className={styles.numeric}>{s.works.toLocaleString()}</td>
              <td>
                <ul>
                  {s.licenses.map(([id, n]) => (
                    <li key={id}>
                      <License id={id} />
                      {s.licenses.length > 1 && <span className={styles.muted}> ({n})</span>}
                    </li>
                  ))}
                </ul>
              </td>
              <td>
                <ul>
                  {s.editions.map((e) => (
                    <li key={e} dir="auto">
                      {e}
                    </li>
                  ))}
                  {s.moreEditions > 0 && (
                    <li className={styles.muted}>and {s.moreEditions} more</li>
                  )}
                  {s.links.map((u) => (
                    <li key={u} className={styles.url}>
                      <a href={u}>{u}</a>
                    </li>
                  ))}
                </ul>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
