import { Suspense } from "react";

import LibraryBrowser from "@/components/LibraryBrowser";

export default function Home() {
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
