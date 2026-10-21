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
          <Link href="/">Search</Link>
          <Link href="/works">Library</Link>
          <Link href="/authors">Authors</Link>
          <Link href="/sources">Sources</Link>
        </nav>
      </div>
    </header>
  );
}
