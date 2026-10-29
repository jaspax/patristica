import type { Metadata } from "next";
import { Suspense } from "react";

import { Hero } from "@/components/Landing";
import SearchPage from "@/components/SearchPage";

// Search results (`/?q=…`) are the same page: robots.txt keeps crawlers off them.
export const metadata: Metadata = { alternates: { canonical: "/" } };

export default function Home() {
  return (
    <main>
      {/* SearchPage reads the URL query, so it renders on the client only. The
          prerendered page shows the landing page's hero meanwhile. */}
      <Suspense
        fallback={
          <>
            <Hero />
            <p>Loading…</p>
          </>
        }
      >
        <SearchPage />
      </Suspense>
    </main>
  );
}
