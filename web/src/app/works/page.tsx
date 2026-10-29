import type { Metadata } from "next";
import { Suspense } from "react";

import LibraryBrowser from "@/components/LibraryBrowser";
import { WorkListing } from "@/components/Prerendered";
import { serverLibraryOrNull } from "@/lib/serverLibrary";

export const metadata: Metadata = {
  title: "Library",
  description:
    "Every work in Patristica: Scripture, the Church Fathers, councils and liturgy of the first thousand years, " +
    "in the original languages and in English translation.",
  alternates: { canonical: "/works" },
};

export default function Library() {
  return (
    <main>
      <h1 className="visually-hidden">Library</h1>
      <Suspense fallback={<p>Loading the library…</p>}>
        <Browser />
      </Suspense>
    </main>
  );
}

/** LibraryBrowser loads the library in the browser; the server's HTML lists every work meanwhile. */
async function Browser() {
  const library = await serverLibraryOrNull();
  return <LibraryBrowser placeholder={library ? <WorkListing library={library} /> : undefined} />;
}
