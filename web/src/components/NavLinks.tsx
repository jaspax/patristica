"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import styles from "./SiteHeader.module.css";

const LINKS = [
  { href: "/", label: "Search" },
  { href: "/works", label: "Library" },
  { href: "/authors", label: "Authors" },
  { href: "/sources", label: "Sources" },
] as const;

/** Whether `pathname` is the page `href` or one of its subpages ("/works/…" is in Library). */
export function isCurrent(href: string, pathname: string): boolean {
  if (href === "/") return pathname === "/";
  return pathname === href || pathname.startsWith(`${href}/`);
}

/** The main navigation, marking the section the reader is in (`pathname`) with aria-current. */
export function Nav({ pathname }: { pathname: string }) {
  return (
    <nav className={styles.nav} aria-label="Main">
      {LINKS.map(({ href, label }) => {
        const current = isCurrent(href, pathname);
        return (
          <Link
            key={href}
            href={href}
            className={styles.navLink}
            aria-current={current ? (pathname === href ? "page" : "location") : undefined}
          >
            {label}
          </Link>
        );
      })}
    </nav>
  );
}

/**
 * The main navigation for the current URL. The path is only known at request
 * time on dynamic routes, so render it inside <Suspense>, with <Nav pathname="" />
 * as the fallback.
 */
export default function NavLinks() {
  return <Nav pathname={usePathname() ?? ""} />;
}
