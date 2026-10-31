import { useCallback, useEffect, useRef, useState } from "react";

/** How long typing pauses before the text is committed (written to the URL). */
export const DEBOUNCE_MS = 250;

export interface DebouncedText {
  /** What the input shows: updated on every keystroke. */
  text: string;
  /** Show `value` now and commit it once typing pauses for `DEBOUNCE_MS`. */
  setText: (value: string) => void;
  /** Show `value` now and drop a pending commit: the caller commits it itself. */
  setNow: (value: string) => void;
}

/**
 * A text input whose committed value lives elsewhere (the URL query), #497.
 *
 * A controlled input fed from the URL waits for a router navigation and a re-render of
 * everything the query filters on each keystroke, and drops keys typed meanwhile. This keeps
 * the typed text in local state and calls `commit` only after a pause. A change to `committed`
 * from elsewhere (Back, a link) is adopted unless a commit is pending: then it is the echo of
 * an older commit, and the newer typing wins.
 */
export function useDebouncedText(
  committed: string,
  commit: (value: string) => void,
  delay: number = DEBOUNCE_MS,
): DebouncedText {
  const [text, setTextState] = useState(committed);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const commitRef = useRef(commit);
  useEffect(() => {
    commitRef.current = commit;
  });

  const cancel = useCallback(() => {
    if (timer.current !== null) clearTimeout(timer.current);
    timer.current = null;
  }, []);

  useEffect(() => {
    if (timer.current === null) setTextState(committed);
  }, [committed]);

  useEffect(() => cancel, [cancel]);

  const setText = useCallback(
    (value: string) => {
      setTextState(value);
      cancel();
      timer.current = setTimeout(() => {
        timer.current = null;
        commitRef.current(value);
      }, delay);
    },
    [cancel, delay],
  );

  const setNow = useCallback(
    (value: string) => {
      cancel();
      setTextState(value);
    },
    [cancel],
  );

  return { text, setText, setNow };
}
