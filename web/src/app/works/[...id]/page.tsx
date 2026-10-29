import type { Metadata } from "next";
import { Suspense } from "react";

import { JsonLd, WorkSummary } from "@/components/Prerendered";
import WorkReader from "@/components/WorkReader";
import { workHref, workIdFromSegments } from "@/lib/library";
import { workDescription, workJsonLd, workTitle } from "@/lib/seo";
import { serverLibraryOrNull } from "@/lib/serverLibrary";

async function findWork(params: PageProps<"/works/[...id]">["params"]) {
  const id = workIdFromSegments((await params).id);
  const library = await serverLibraryOrNull();
  return { id, library, row: library?.index.works.find((w) => w.id === id) };
}

export async function generateMetadata({ params }: PageProps<"/works/[...id]">): Promise<Metadata> {
  const { library, row } = await findWork(params);
  if (!library) return {};
  if (!row) return { title: "Work not found", robots: { index: false } };
  const title = workTitle(row, library.authors, library.index);
  const description = workDescription(row, library.authors, library.index);
  return {
    title,
    description,
    alternates: { canonical: workHref(row.id) },
    openGraph: { title, description, url: workHref(row.id), type: "article" },
  };
}

export default function WorkPage({ params }: PageProps<"/works/[...id]">) {
  return (
    <main>
      <Suspense fallback={<p>Loading…</p>}>
        <Work params={params} />
      </Suspense>
    </main>
  );
}

async function Work({ params }: { params: PageProps<"/works/[...id]">["params"] }) {
  const { library, row } = await findWork(params);
  return (
    <>
      {library && row && <JsonLd data={workJsonLd(row, library.authors, library.index)} />}
      {/* The reader loads the work from the static library in the browser; the
          server's HTML has its header and links meanwhile. */}
      <WorkReader placeholder={library && row ? <WorkSummary row={row} library={library} /> : undefined} />
    </>
  );
}
