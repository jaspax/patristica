import type { Metadata } from "next";
import { Suspense } from "react";

import SearchPage from "@/components/SearchPage";

export const metadata: Metadata = { title: "Search" };

export default function Search() {
  return (
    <main>
      <h1 className="visually-hidden">Search</h1>
      {/* SearchPage reads the URL query, so it renders on the client only. */}
      <Suspense fallback={<p>Loading…</p>}>
        <SearchPage />
      </Suspense>
    </main>
  );
}
