import { act, cleanup, render } from "@testing-library/react";
import { useRef } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { useOffscreen } from "./useOffscreen";

type Callback = (entries: Partial<IntersectionObserverEntry>[]) => void;
let notify: Callback = () => {};

function Probe() {
  const ref = useRef<HTMLParagraphElement>(null);
  const offscreen = useOffscreen(ref);
  return <p ref={ref}>{offscreen ? "off" : "on"}</p>;
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("useOffscreen", () => {
  it("follows the observer", () => {
    const observe = vi.fn();
    vi.stubGlobal(
      "IntersectionObserver",
      class {
        constructor(cb: Callback) {
          notify = cb;
        }
        observe = observe;
        disconnect() {}
      },
    );
    const { container } = render(<Probe />);
    expect(observe).toHaveBeenCalledWith(container.querySelector("p"));
    expect(container.textContent).toBe("on");
    act(() => notify([{ isIntersecting: false }]));
    expect(container.textContent).toBe("off");
    act(() => notify([{ isIntersecting: true }]));
    expect(container.textContent).toBe("on");
  });

  it("is false where IntersectionObserver is missing", () => {
    vi.stubGlobal("IntersectionObserver", undefined);
    const { container } = render(<Probe />);
    expect(container.textContent).toBe("on");
  });
});
