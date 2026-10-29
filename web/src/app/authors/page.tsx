import type { Metadata } from "next";
import { Suspense } from "react";

import AuthorList from "@/components/AuthorList";
import { AuthorListing } from "@/components/Prerendered";
import { serverLibraryOrNull } from "@/lib/serverLibrary";

import styles from "./page.module.css";

export const metadata: Metadata = {
  title: "Authors",
  description:
    "The Church Fathers and other authors of the first thousand years of Christianity in Patristica, " +
    "with their dates and every work of theirs in the library.",
  alternates: { canonical: "/authors" },
};

export default function AuthorsPage() {
  return (
    <main>
      <h1 className={styles.title}>Authors</h1>
      <Suspense fallback={<p>Loading…</p>}>
        <Authors />
      </Suspense>
    </main>
  );
}

/** AuthorList loads the library in the browser; the server's HTML lists every author meanwhile. */
async function Authors() {
  const library = await serverLibraryOrNull();
  return <AuthorList placeholder={library ? <AuthorListing library={library} /> : undefined} />;
}
