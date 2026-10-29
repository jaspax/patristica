import type { Metadata } from "next";
import { Suspense } from "react";

import SourcesTable from "@/components/SourcesTable";

import styles from "./page.module.css";

export const metadata: Metadata = { title: "Sources & licences", alternates: { canonical: "/sources" } };

const REPO = "https://github.com/jaspax/patristica/blob/master";

export default function SourcesPage() {
  return (
    <main>
      <h1 className={styles.title}>Sources &amp; licences</h1>
      <div className={styles.intro}>
        <p>
          Every text in Patristica keeps the licence of the edition it comes from, and our changes
          to a text (cleanup, chunking, references) are shared under that same licence. Catalogue
          metadata we created ourselves is dedicated to the public domain (CC0), and the
          software is under the <a href={`${REPO}/LICENSE`}>MIT License</a>. Details are in{" "}
          <a href={`${REPO}/DATA_LICENSE.md`}>DATA_LICENSE.md</a>.
        </p>
        <p>
          Collections marked <span className={styles.nc}>non-commercial</span> include texts that may
          not be used commercially, so Patristica is a non-commercial project. When you reuse a
          text, credit it as the reader does: title, author, collection, edition, licence and
          source link.
        </p>
      </div>
      <Suspense fallback={<p>Loading…</p>}>
        <SourcesTable />
      </Suspense>
    </main>
  );
}
