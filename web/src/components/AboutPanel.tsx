"use client";

import { loadAbout } from "@/lib/library";
import { useLoaded } from "@/lib/useLoaded";

import styles from "./AboutPanel.module.css";

/**
 * A work's description or an author's bio (#795), beside the page header's
 * facts. `file` is its library file (workAboutFile / authorAboutFile); render
 * this only when the row or author has one. Nothing shows while it loads or if
 * the load fails: the page is complete without it.
 */
export default function AboutPanel({ file, label }: { file: string; label: string }) {
  const about = useLoaded(() => loadAbout(file));
  if (about.status !== "ready") return null;
  const { text, wikipedia } = about.data;
  return (
    <aside className={styles.about} aria-label={label}>
      <p className={styles.text}>{text}</p>
      {wikipedia && (
        <p className={styles.foot}>
          <a href={wikipedia} rel="external">
            Wikipedia
          </a>
        </p>
      )}
    </aside>
  );
}
