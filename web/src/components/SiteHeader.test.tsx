import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import SiteHeader from "./SiteHeader";

afterEach(cleanup);

describe("SiteHeader", () => {
  it("links Search, Library, Authors and Sources, in that order", () => {
    render(<SiteHeader />);
    const links = within(screen.getByRole("navigation", { name: "Main" })).getAllByRole("link");
    expect(links.map((a) => [a.textContent, a.getAttribute("href")])).toEqual([
      ["Search", "/"],
      ["Library", "/works"],
      ["Authors", "/authors"],
      ["Sources", "/sources"],
    ]);
  });

  it("has no search box of its own", () => {
    render(<SiteHeader />);
    expect(screen.queryByRole("searchbox")).toBeNull();
  });
});
