import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { DEBOUNCE_MS, useDebouncedText } from "./useDebouncedText";

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

function setup(initial = "") {
  const commit = vi.fn();
  const hook = renderHook(({ committed }) => useDebouncedText(committed, commit), {
    initialProps: { committed: initial },
  });
  return { commit, hook };
}

describe("useDebouncedText", () => {
  it("starts from the committed value", () => {
    const { hook } = setup("aug");
    expect(hook.result.current.text).toBe("aug");
  });

  it("shows each keystroke at once and commits only the last one after a pause", () => {
    const { commit, hook } = setup();
    for (const value of ["b", "ba", "bas"]) {
      act(() => hook.result.current.setText(value));
      expect(hook.result.current.text).toBe(value);
    }
    expect(commit).not.toHaveBeenCalled();
    act(() => vi.advanceTimersByTime(DEBOUNCE_MS));
    expect(commit).toHaveBeenCalledTimes(1);
    expect(commit).toHaveBeenCalledWith("bas");
  });

  it("adopts a committed value changed elsewhere", () => {
    const { hook } = setup("aug");
    hook.rerender({ committed: "basil" });
    expect(hook.result.current.text).toBe("basil");
  });

  it("keeps newer typing over the echo of an older commit", () => {
    const { commit, hook } = setup();
    act(() => hook.result.current.setText("ba"));
    act(() => vi.advanceTimersByTime(DEBOUNCE_MS));
    act(() => hook.result.current.setText("bas"));
    // The URL catches up with the first commit while "bas" is pending.
    hook.rerender({ committed: "ba" });
    expect(hook.result.current.text).toBe("bas");
    act(() => vi.advanceTimersByTime(DEBOUNCE_MS));
    expect(commit).toHaveBeenLastCalledWith("bas");
  });

  it("setNow drops a pending commit", () => {
    const { commit, hook } = setup();
    act(() => hook.result.current.setText("bas"));
    act(() => hook.result.current.setNow(""));
    expect(hook.result.current.text).toBe("");
    act(() => vi.advanceTimersByTime(DEBOUNCE_MS));
    expect(commit).not.toHaveBeenCalled();
  });

  it("commits nothing after unmounting", () => {
    const { commit, hook } = setup();
    act(() => hook.result.current.setText("bas"));
    hook.unmount();
    act(() => vi.advanceTimersByTime(DEBOUNCE_MS));
    expect(commit).not.toHaveBeenCalled();
  });
});
