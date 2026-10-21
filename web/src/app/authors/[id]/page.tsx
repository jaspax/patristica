import { Suspense } from "react";

import AuthorPage from "@/components/AuthorPage";

export default function AuthorRoute() {
  return (
    <main>
      {/* The author page loads the author index from the static library in the browser. */}
      <Suspense fallback={<p>Loading…</p>}>
        <AuthorPage />
      </Suspense>
    </main>
  );
}
