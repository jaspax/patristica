"use client";

import { useEffect, useState, type RefObject } from "react";

/**
 * True while the element in `ref` is out of the viewport (after it has been
 * on the page). False until the first observation, and always false where
 * IntersectionObserver is missing, so nothing that depends on it appears
 * unexpectedly.
 */
export function useOffscreen(ref: RefObject<Element | null>): boolean {
  const [offscreen, setOffscreen] = useState(false);
  useEffect(() => {
    const el = ref.current;
    if (!el || typeof IntersectionObserver === "undefined") return;
    const observer = new IntersectionObserver((entries) => {
      const last = entries[entries.length - 1];
      if (last) setOffscreen(!last.isIntersecting);
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, [ref]);
  return offscreen;
}
