import Link from "next/link";
import { Suspense } from "react";

import BrandMark from "./BrandMark";
import NavLinks, { Nav } from "./NavLinks";
import styles from "./SiteHeader.module.css";

export default function SiteHeader() {
  return (
    <header className={styles.header}>
      <a href="#content" className="skip-link">
        Skip to content
      </a>
      <div className={styles.inner}>
        <Link href="/" className={styles.brand}>
          <BrandMark className={styles.mark} />
          <span className={styles.wordmark}>Patristica</span>
          <span className={styles.tagline}>Scripture &amp; the Fathers · the first millennium</span>
        </Link>
        <Suspense fallback={<Nav pathname="" />}>
          <NavLinks />
        </Suspense>
      </div>
    </header>
  );
}
