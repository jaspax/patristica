import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import SiteFooter from "./SiteFooter";

afterEach(cleanup);

describe("SiteFooter", () => {
  it("repeats the main sections in its own navigation", () => {
    render(<SiteFooter />);
    const links = within(screen.getByRole("navigation", { name: "Footer" })).getAllByRole("link");
    expect(links.map((a) => a.getAttribute("href"))).toEqual(["/", "/works", "/authors", "/sources"]);
  });

  it("points to the licences of the texts", () => {
    render(<SiteFooter />);
    expect(screen.getByText(/keeps the licence and attribution/)).toBeTruthy();
  });
});
