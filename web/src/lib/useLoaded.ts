"use client";

import { useEffect, useState } from "react";

export type Loaded<T> =
  | { status: "loading" }
  | { status: "ready"; data: T }
  | { status: "error"; error: string };

/**
 * Run `load` once after mount, in the browser only (library files are fetched
 * from a relative URL, which doesn't work during server rendering). To load
 * something else, remount the component with a different `key`.
 */
export function useLoaded<T>(load: () => Promise<T>): Loaded<T> {
  const [state, setState] = useState<Loaded<T>>({ status: "loading" });
  useEffect(() => {
    let live = true;
    load().then(
      (data) => live && setState({ status: "ready", data }),
      (err: unknown) => live && setState({ status: "error", error: String(err) }),
    );
    return () => {
      live = false;
    };
    // `load` runs once per mount by design (see above).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  return state;
}
