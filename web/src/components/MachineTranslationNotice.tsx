import { languageInfo } from "@/lib/lang";
import type { WorkRow } from "@/lib/library";

import { VersionLink, type PositionFor } from "./VersionSwitcher";
import styles from "./MachineTranslationNotice.module.css";

/**
 * The disclaimer at the top of a machine-translated work (#422), linking the
 * original it was translated from (when the library has it) at the reader's place.
 */
export default function MachineTranslationNotice({
  original,
  positionFor,
}: {
  original?: WorkRow;
  positionFor?: PositionFor;
}) {
  const source = original ? (
    <>
      the{" "}
      <VersionLink target={original} positionFor={positionFor}>
        {languageInfo(original.language).name} original
      </VersionLink>
    </>
  ) : (
    "the original"
  );
  return (
    <aside className={styles.notice} role="note" aria-label="Machine translation">
      This English text was machine-translated from {source} by an AI model and has not been reviewed. It may contain
      errors; consult the original for close study.
    </aside>
  );
}
