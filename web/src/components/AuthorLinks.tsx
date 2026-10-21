import Link from "next/link";
import { Fragment } from "react";

import { authorHref, type AuthorRef } from "@/lib/library";

/** A work's authors, each linked to its author page (unlinked when not in the author index). */
export default function AuthorLinks({ authors }: { authors: AuthorRef[] }) {
  return authors.map((a, i) => (
    <Fragment key={a.id ?? a.name}>
      {i > 0 && ", "}
      {a.id ? <Link href={authorHref(a.id)}>{a.name}</Link> : a.name}
    </Fragment>
  ));
}
