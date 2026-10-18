import { cleanup, render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { fragmentId, TARGET_ATTRIBUTE, useHashTarget } from "./useHashTarget";

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
  window.location.hash = "";
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

  it("follows fragment changes, including derived verses", () => {
    window.location.hash = "#Gen.1.1";
    const { container } = render(<Text ready />);
    window.location.hash = "#Hymn.1.2.s3";
    window.dispatchEvent(new HashChangeEvent("hashchange"));
    const marked = container.querySelectorAll(`[${TARGET_ATTRIBUTE}]`);
    expect([...marked].map((e) => e.id)).toEqual(["Hymn.1.2.s3"]);
  });

  it("does nothing for an unknown fragment", () => {
    window.location.hash = "#Nowhere.1";
    const { container } = render(<Text ready />);
    expect(scrolled).not.toHaveBeenCalled();
    expect(container.querySelector(`[${TARGET_ATTRIBUTE}]`)).toBeNull();
  });
});
