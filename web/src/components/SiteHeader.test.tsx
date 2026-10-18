import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import SiteHeader from "./SiteHeader";

// next/form needs the app router; a plain form is enough to check the markup.
vi.mock("next/form", () => ({
  default: (props: React.ComponentProps<"form">) => <form {...props} />,
}));

afterEach(cleanup);

describe("SiteHeader", () => {
  it("has a search bar that opens /search?q=…", () => {
    render(<SiteHeader />);
    const form = screen.getByRole("search");
    expect(form.getAttribute("action")).toBe("/search");
    expect(screen.getByRole("searchbox", { name: "Search the texts" }).getAttribute("name")).toBe("q");
    expect(screen.getByRole("link", { name: "Search" }).getAttribute("href")).toBe("/search");
  });
});
