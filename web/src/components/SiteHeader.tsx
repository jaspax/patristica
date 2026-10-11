import Link from "next/link";

import styles from "./SiteHeader.module.css";

export default function SiteHeader() {
  return (
    <header className={styles.header}>
      <div className={styles.inner}>
        <Link href="/" className={styles.brand}>
          Patristica
        </Link>
        <nav className={styles.nav} aria-label="Main">
          <Link href="/">Library</Link>
          <Link href="/sources">Sources</Link>
          <span className={styles.disabled} aria-disabled="true" title="Coming soon">
            Search
          </span>
        </nav>
      </div>
    </header>
  );
}
