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

  it("gives a rubric span the rubric style, not the neutral marker", () => {
    const { container } = render(
      <p>
        <EditorialText text="ΧΟΡΟΣ· Ἀμήν." spans={[[0, 6, "rubric"]]} />
      </p>,
    );
    const marked = container.querySelector("[data-editorial]");
    expect(marked?.textContent).toBe("ΧΟΡΟΣ·");
    expect(marked?.getAttribute("title")).toBe("Rubric");
    expect(marked?.className).toMatch(/rubric/);
    expect(marked?.className).not.toMatch(/editorial/);
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
