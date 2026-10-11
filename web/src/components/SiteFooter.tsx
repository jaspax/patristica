import Link from "next/link";

import styles from "./SiteFooter.module.css";

export default function SiteFooter() {
  return (
    <footer className={styles.footer}>
      <div className={styles.inner}>
        Scripture and patristic texts of the first millennium. Each text keeps the licence and
        attribution of its source edition, shown with the text; see{" "}
        <Link href="/sources">Sources &amp; licences</Link>. Software under the MIT License.
      </div>
    </footer>
  );
}
