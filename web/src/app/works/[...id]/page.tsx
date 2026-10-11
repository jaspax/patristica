import { Suspense } from "react";

import WorkReader from "@/components/WorkReader";

export default function WorkPage() {
  return (
    <main>
      {/* The reader loads the work from the static library in the browser. */}
      <Suspense fallback={<p>Loading…</p>}>
        <WorkReader />
      </Suspense>
    </main>
  );
}
