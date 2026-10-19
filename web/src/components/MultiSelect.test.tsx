import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import MultiSelect from "./MultiSelect";

afterEach(cleanup);

const options = [
  { value: "grc", label: "Greek" },
  { value: "lat", label: "Latin" },
  { value: "syc", label: "Syriac", count: 12 },
];

function setup(selected: string[] = [], searchable = false) {
  const onChange = vi.fn();
  render(
    <>
      <MultiSelect label="Language" options={options} selected={selected} onChange={onChange} searchable={searchable} />
      <button type="button">elsewhere</button>
    </>,
  );
  const trigger = screen.getByRole("button", { name: /^Language/ });
  return { onChange, trigger };
}

describe("MultiSelect", () => {
  it("names the selection on its button", () => {
    setup(["grc", "syc"]);
    expect(screen.getByRole("button", { name: "Language Greek, Syriac" })).toBeTruthy();
    cleanup();
    setup();
    expect(screen.getByRole("button", { name: "Language All" }).getAttribute("aria-expanded")).toBe("false");
  });

  it("applies the ticked values once, when Done closes the panel", () => {
    const { onChange, trigger } = setup(["grc"]);
    fireEvent.click(trigger);
    const panel = screen.getByRole("group", { name: "Language" });
    fireEvent.click(within(panel).getByRole("checkbox", { name: "Latin" }));
    fireEvent.click(within(panel).getByRole("checkbox", { name: "Greek" }));
    expect(onChange).not.toHaveBeenCalled();
    expect(trigger.getAttribute("aria-expanded")).toBe("true");
    fireEvent.click(within(panel).getByRole("button", { name: "Done" }));
    expect(onChange).toHaveBeenCalledExactlyOnceWith(["lat"]);
    expect(screen.queryByRole("group")).toBeNull();
    expect(document.activeElement).toBe(trigger);
  });

  it("applies on Escape and when focus leaves, and not at all when nothing changed", () => {
    const { onChange, trigger } = setup();
    fireEvent.click(trigger);
    fireEvent.keyDown(trigger, { key: "Escape" });
    expect(onChange).not.toHaveBeenCalled();
    expect(screen.queryByRole("group")).toBeNull();

    fireEvent.click(trigger);
    const box = screen.getByRole("checkbox", { name: "Syriac 12" });
    fireEvent.click(box);
    fireEvent.blur(box, { relatedTarget: screen.getByRole("button", { name: "elsewhere" }) });
    expect(onChange).toHaveBeenCalledExactlyOnceWith(["syc"]);
  });

  it("clears the draft", () => {
    const { onChange, trigger } = setup(["grc", "lat"]);
    fireEvent.click(trigger);
    fireEvent.click(screen.getByRole("button", { name: "Clear" }));
    fireEvent.click(screen.getByRole("button", { name: "Done" }));
    expect(onChange).toHaveBeenCalledExactlyOnceWith([]);
  });

  it("narrows a long list with the find box, ignoring accents and case", () => {
    const { trigger } = setup([], true);
    fireEvent.click(trigger);
    fireEvent.change(screen.getByRole("searchbox", { name: "Find language" }), { target: { value: "LÁT" } });
    expect(screen.getAllByRole("checkbox").map((c) => c.closest("label")!.textContent)).toEqual(["Latin"]);
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "coptic" } });
    expect(screen.getByText("No matches.")).toBeTruthy();
  });
});
