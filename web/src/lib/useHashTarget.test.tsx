import { cleanup, render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { byId, derivedFallbacks, fragmentId, noHighlight, TARGET_ATTRIBUTE, useHashTarget } from "./useHashTarget";

function Text({ ready }: { ready: boolean }) {
  useHashTarget(ready);
  return ready ? (
    <div>
      <p id="Gen.1.1">In the beginning</p>
      <span id="Hymn.1.2.s3">derived</span>
    </div>
  ) : null;
}

const scrolled = vi.fn();

beforeEach(() => {
  scrolled.mockReset();
  // jsdom has no layout: record scrolls instead.
  Element.prototype.scrollIntoView = function (this: Element) {
    scrolled(this.id);
  };
});

afterEach(() => {
  cleanup();
  window.history.replaceState(null, "", "/");
});

describe("fragmentId", () => {
  it("decodes the fragment", () => {
    expect(fragmentId("#Gen.1.1")).toBe("Gen.1.1");
    expect(fragmentId("#Hymn%201.2")).toBe("Hymn 1.2");
    expect(fragmentId("#100%")).toBe("100%");
    expect(fragmentId("")).toBe("");
  });
});

describe("useHashTarget", () => {
  it("waits for the text, then scrolls to and marks the target", () => {
    window.location.hash = "#Gen.1.1";
    const { rerender, container } = render(<Text ready={false} />);
    expect(scrolled).not.toHaveBeenCalled();
    rerender(<Text ready />);
    expect(scrolled).toHaveBeenCalledWith("Gen.1.1");
    expect(container.querySelector(`[${TARGET_ATTRIBUTE}]`)?.id).toBe("Gen.1.1");
  });

  it("opens a derived verse that is gone at its unit or section heading (#122)", () => {
    window.location.hash = "#Gen.1.1.s4";
    render(<Text ready />);
    expect(scrolled).toHaveBeenCalledWith("Gen.1.1");
  });

  it("follows fragment changes, including derived verses", () => {
    window.location.hash = "#Gen.1.1";
    const { container } = render(<Text ready />);
    window.location.hash = "#Hymn.1.2.s3";
    window.dispatchEvent(new HashChangeEvent("hashchange"));
    const marked = container.querySelectorAll(`[${TARGET_ATTRIBUTE}]`);
    expect([...marked].map((e) => e.id)).toEqual(["Hymn.1.2.s3"]);
  });

  it("with ?nohl, scrolls to the opening fragment without marking it", () => {
    window.history.replaceState(null, "", "/works/x?nohl#Gen.1.1");
    const { container } = render(<Text ready />);
    expect(scrolled).toHaveBeenCalledWith("Gen.1.1");
    expect(container.querySelector(`[${TARGET_ATTRIBUTE}]`)).toBeNull();
    // A fragment the reader then follows is highlighted as usual.
    window.location.hash = "#Hymn.1.2.s3";
    window.dispatchEvent(new HashChangeEvent("hashchange"));
    expect(scrolled).toHaveBeenLastCalledWith("Hymn.1.2.s3");
    expect(container.querySelector(`[${TARGET_ATTRIBUTE}]`)?.id).toBe("Hymn.1.2.s3");
  });

  it("reads nohl from the query only", () => {
    expect(noHighlight("?nohl")).toBe(true);
    expect(noHighlight("?q=x&nohl")).toBe(true);
    expect(noHighlight("")).toBe(false);
    expect(noHighlight("?q=nohl")).toBe(false);
  });

  it("does nothing for an unknown fragment", () => {
    window.location.hash = "#Nowhere.1";
    const { container } = render(<Text ready />);
    expect(scrolled).not.toHaveBeenCalled();
    expect(container.querySelector(`[${TARGET_ATTRIBUTE}]`)).toBeNull();
  });
});

describe("derivedFallbacks", () => {
  it("tries the paragraph, then its first derived verse (#200)", () => {
    expect(derivedFallbacks("Aug.Ep.3.s7")).toEqual(["Aug.Ep.3", "Aug.Ep.3.s1"]);
    expect(derivedFallbacks("Gen.1.1")).toEqual([]);
  });

  it("finds a moved derived verse at its paragraph's first verse", () => {
    render(
      <div>
        <span id="Ep.2.s1">first</span>
        <span id="Ep.2.s2">second</span>
      </div>,
    );
    expect(byId("Ep.2.s9")?.id).toBe("Ep.2.s1");
    expect(byId("Ep.2.s2")?.id).toBe("Ep.2.s2");
    expect(byId("Ep.4.s1")).toBeNull();
  });
});
