import Link from "next/link";

import BrandMark from "./BrandMark";
import styles from "./SiteFooter.module.css";

export default function SiteFooter() {
  return (
    <footer className={styles.footer}>
      <div className={styles.inner}>
        <div className={styles.brand}>
          <BrandMark className={styles.mark} />
          <span>Patristica</span>
        </div>
        <nav className={styles.links} aria-label="Footer">
          <Link href="/">Search</Link>
          <Link href="/works">Library</Link>
          <Link href="/authors">Authors</Link>
          <Link href="/sources">Sources &amp; licences</Link>
        </nav>
        <p className={styles.note}>
          Scripture and patristic texts of the first millennium. Each text keeps the licence and attribution of
          its source edition, shown with the text; see <Link href="/sources">Sources &amp; licences</Link>.
          Software under the MIT License.
        </p>
      </div>
    </footer>
  );
}
