import type { Metadata } from "next";
import { Suspense } from "react";

import AuthorList from "@/components/AuthorList";

import styles from "./page.module.css";

export const metadata: Metadata = { title: "Authors" };

export default function AuthorsPage() {
  return (
    <main>
      <h1 className={styles.title}>Authors</h1>
      <Suspense fallback={<p>Loading…</p>}>
        <AuthorList />
      </Suspense>
    </main>
  );
}
