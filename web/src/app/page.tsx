import { Suspense } from "react";

import { Hero } from "@/components/Landing";
import SearchPage from "@/components/SearchPage";

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
