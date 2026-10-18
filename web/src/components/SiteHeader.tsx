import Form from "next/form";
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
          <Link href="/authors">Authors</Link>
          <Link href="/sources">Sources</Link>
          <Link href="/search">Search</Link>
        </nav>
        {/* A GET form: /search?q=…, with client-side navigation (and without JS). */}
        <Form action="/search" role="search" className={styles.search}>
          <input type="search" name="q" aria-label="Search the texts" placeholder="Search the texts" maxLength={500} />
        </Form>
      </div>
    </header>
  );
}
