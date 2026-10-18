"use client";

import { useEffect } from "react";

/** Attribute set on the element the URL fragment names (styled in WorkText.module.css). */
export const TARGET_ATTRIBUTE = "data-target";

/** The element id in a URL fragment ("#Gen.1.1" → "Gen.1.1"), or "" if there is none. */
export function fragmentId(hash: string): string {
  const raw = hash.startsWith("#") ? hash.slice(1) : hash;
  try {
    return decodeURIComponent(raw);
  } catch {
    return raw;
  }
}

/**
 * Scroll `el` into view and keep it there while the layout settles. With
 * `content-visibility: auto`, sections are laid out at an estimated height
 * until they are rendered, so the first scroll can land off target; scroll
 * again on each frame until the element stays put (at most `maxFrames`).
 */
export function settleScroll(el: Element, maxFrames = 60): () => void {
  let frame = 0;
  let handle = 0;
  let last = Number.NaN;
  let stable = 0;
  const step = () => {
    const top = el.getBoundingClientRect().top;
    if (Math.abs(top - last) < 1) {
      stable += 1;
    } else {
      stable = 0;
      el.scrollIntoView({ block: "start" });
      last = el.getBoundingClientRect().top;
    }
    frame += 1;
    if (stable < 3 && frame < maxFrames) handle = requestAnimationFrame(step);
  };
  el.scrollIntoView({ block: "start" });
  last = el.getBoundingClientRect().top;
  handle = requestAnimationFrame(step);
  return () => cancelAnimationFrame(handle);
}

/**
 * Once `ready` (the text is rendered), scroll to the element the URL fragment
 * names and mark it with TARGET_ATTRIBUTE; follow later fragment changes.
 * The text loads after navigation, so the browser's own jump finds nothing.
 */
export function useHashTarget(ready: boolean): void {
  useEffect(() => {
    if (!ready) return;
    let marked: Element | null = null;
    let cancel = () => {};
    const go = () => {
      cancel();
      marked?.removeAttribute(TARGET_ATTRIBUTE);
      marked = null;
      const id = fragmentId(window.location.hash);
      const el = id ? document.getElementById(id) : null;
      if (!el) return;
      el.setAttribute(TARGET_ATTRIBUTE, "");
      marked = el;
      cancel = settleScroll(el);
    };
    go();
    window.addEventListener("hashchange", go);
    return () => {
      window.removeEventListener("hashchange", go);
      cancel();
      marked?.removeAttribute(TARGET_ATTRIBUTE);
    };
  }, [ready]);
}
