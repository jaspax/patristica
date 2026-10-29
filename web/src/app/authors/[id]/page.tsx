import type { Metadata } from "next";
import { Suspense } from "react";

import AuthorPage from "@/components/AuthorPage";
import { AuthorSummary, JsonLd } from "@/components/Prerendered";
import { formatLifespan } from "@/lib/format";
import { authorHref } from "@/lib/library";
import { authorDescription, authorJsonLd, worksOf } from "@/lib/seo";
import { serverLibraryOrNull } from "@/lib/serverLibrary";

async function findAuthor(params: PageProps<"/authors/[id]">["params"]) {
  const id = decodeURIComponent((await params).id);
  const library = await serverLibraryOrNull();
  const author = library?.authors.get(id);
  if (!library || !author) return { library, author: undefined, works: [], description: "" };
  const works = worksOf(library.index, author.id);
  return { library, author, works, description: authorDescription(author, works, formatLifespan(author)) };
}

export async function generateMetadata({ params }: PageProps<"/authors/[id]">): Promise<Metadata> {
  const { library, author, works, description } = await findAuthor(params);
  if (!library) return {};
  if (!author) return { title: "Author not found", robots: { index: false } };
  return {
    title: author.name,
    description,
    alternates: { canonical: authorHref(author.id) },
    openGraph: { title: author.name, description, url: authorHref(author.id), type: "profile" },
    // A page with no works (an author known only from the index) has nothing to find.
    ...(works.length === 0 ? { robots: { index: false } } : {}),
  };
}

export default function AuthorRoute({ params }: PageProps<"/authors/[id]">) {
  return (
    <main>
      <Suspense fallback={<p>Loading…</p>}>
        <Author params={params} />
      </Suspense>
    </main>
  );
}

async function Author({ params }: { params: PageProps<"/authors/[id]">["params"] }) {
  const { library, author, works, description } = await findAuthor(params);
  return (
    <>
      {author && <JsonLd data={authorJsonLd(author, description)} />}
      {/* The author page loads the author index from the static library in the
          browser; the server's HTML has its header and work list meanwhile. */}
      <AuthorPage
        placeholder={library && author ? <AuthorSummary author={author} works={works} library={library} /> : undefined}
      />
    </>
  );
}
