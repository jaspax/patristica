import type { Metadata } from "next";
import { Suspense } from "react";

import LibraryBrowser from "@/components/LibraryBrowser";

export const metadata: Metadata = { title: "Library" };

export default function Library() {
  return (
    <main>
      <h1 className="visually-hidden">Library</h1>
      {/* LibraryBrowser reads the URL query, so it renders on the client only. */}
      <Suspense fallback={<p>Loading the library…</p>}>
        <LibraryBrowser />
      </Suspense>
    </main>
  );
}
