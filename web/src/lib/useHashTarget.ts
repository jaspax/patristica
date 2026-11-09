"use client";

import { useEffect } from "react";

import { isDerivedRef } from "./render";

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
 * Query parameter that opens the page at its fragment without highlighting
 * it: a version switch from the reader's scroll position (`?nohl#Ps.22.1`),
 * where the reader chose no passage. It applies only to the fragment the page
 * opens at; later fragment changes highlight as usual.
 */
export const NO_HIGHLIGHT_PARAM = "nohl";

/** True if the URL's query (`location.search`) asks not to highlight the opening fragment. */
export function noHighlight(search: string): boolean {
  return new URLSearchParams(search).has(NO_HIGHLIGHT_PARAM);
}

/**
 * Once `ready` (the text is rendered), scroll to the element the URL fragment
 * names and mark it with TARGET_ATTRIBUTE; follow later fragment changes.
 * The text loads after navigation, so the browser's own jump finds nothing.
 * With `?nohl` the opening fragment is scrolled to but not marked. The query
 * is read from `window.location` in the effect, like the fragment, which
 * `useSearchParams` can't see; that also spares the reader the Suspense
 * boundary `useSearchParams` needs in a prerendered route.
 *
 * `resolve` finds the element for a fragment id (by default the element with
 * that id); parallel reading also looks in the other versions' columns. It
 * is read when `ready` turns true.
 */
export function useHashTarget(ready: boolean, resolve: (id: string) => Element | null = byId): void {
  useEffect(() => {
    if (!ready) return;
    let marked: Element | null = null;
    let cancel = () => {};
    const go = (highlight: boolean) => {
      cancel();
      marked?.removeAttribute(TARGET_ATTRIBUTE);
      marked = null;
      const id = fragmentId(window.location.hash);
      const el = id ? resolve(id) : null;
      if (!el) return;
      if (highlight) {
        el.setAttribute(TARGET_ATTRIBUTE, "");
        marked = el;
      }
      cancel = settleScroll(el);
    };
    const onHashChange = () => go(true);
    go(!noHighlight(window.location.search));
    window.addEventListener("hashchange", onHashChange);
    return () => {
      window.removeEventListener("hashchange", onHashChange);
      cancel();
      marked?.removeAttribute(TARGET_ATTRIBUTE);
    };
    // `resolve` is read once the text is ready, by design (see above).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready]);
}

/**
 * Ids to try, in order, for a derived verse (`Did.1.s3`) that isn't on the
 * page: its unit (`Did.1`, also the section heading that took over that ref
 * when the unit was cut into printed verses, #122), then the unit's first
 * derived verse (`Did.1.s1`). A link to a derived verse that a re-cut moved
 * or removed (#200: cuts anchored on the original) lands on its paragraph,
 * whose ref never changes. Empty for any other ref.
 */
export function derivedFallbacks(id: string): string[] {
  if (!isDerivedRef(id)) return [];
  const unit = id.slice(0, id.lastIndexOf("."));
  return [unit, `${unit}.s1`];
}

/** The element with id `id`, or for a derived verse that isn't on the page, its paragraph. */
export function byId(id: string): Element | null {
  for (const candidate of [id, ...derivedFallbacks(id)]) {
    const el = document.getElementById(candidate);
    if (el) return el;
  }
  return null;
}
