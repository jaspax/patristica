import { Fragment } from "react";

import { editorialSegments } from "@/lib/editorial";
import type { EditorialSpan } from "@/lib/library";

import styles from "./EditorialText.module.css";

/**
 * A chunk's text with its editorial material (#236) marked. The marker is
 * deliberately neutral; the dedicated style per kind is #291.
 */
export default function EditorialText({ text, spans }: { text: string; spans?: readonly EditorialSpan[] }) {
  if (!spans || spans.length === 0) return <>{text}</>;
  return (
    <>
      {editorialSegments(text, spans).map((s, i) =>
        s.kind === null ? (
          <Fragment key={i}>{s.text}</Fragment>
        ) : (
          <span key={i} className={styles.editorial} data-editorial={s.kind} title={`Editorial (${s.kind})`}>
            {s.text}
          </span>
        ),
      )}
    </>
  );
}
