import { cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import EditorialText from "./EditorialText";

afterEach(cleanup);

describe("EditorialText", () => {
  it("keeps the whole text and marks the editorial spans", () => {
    const { container } = render(
      <p>
        <EditorialText text="ⲁⲩⲱ […] ⲁϥ" spans={[[4, 7, "lacuna"]]} />
      </p>,
    );
    expect(container.textContent).toBe("ⲁⲩⲱ […] ⲁϥ");
    const marked = container.querySelectorAll("[data-editorial]");
    expect([...marked].map((m) => [m.textContent, m.getAttribute("data-editorial")])).toEqual([
      ["[…]", "lacuna"],
    ]);
  });

  it("renders plain text without spans", () => {
    const { container } = render(
      <p>
        <EditorialText text="ⲁⲩⲱ ⲁϥ" />
      </p>,
    );
    expect(container.innerHTML).toBe("<p>ⲁⲩⲱ ⲁϥ</p>");
  });
});
