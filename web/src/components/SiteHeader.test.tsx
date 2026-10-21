import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { isCurrent } from "./NavLinks";
import SiteHeader from "./SiteHeader";

let pathname = "/";
vi.mock("next/navigation", () => ({ usePathname: () => pathname }));

afterEach(() => {
  cleanup();
  pathname = "/";
});

function navLinks() {
  return within(screen.getByRole("navigation", { name: "Main" })).getAllByRole("link");
}

describe("SiteHeader", () => {
  it("links Search, Library, Authors and Sources, in that order", () => {
    render(<SiteHeader />);
    expect(navLinks().map((a) => [a.textContent, a.getAttribute("href")])).toEqual([
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

  it("links home through the wordmark", () => {
    render(<SiteHeader />);
    const home = screen.getAllByRole("link").find((a) => a.textContent?.startsWith("Patristica"));
    expect(home?.getAttribute("href")).toBe("/");
  });

  it("starts with a skip link to the content", () => {
    render(<SiteHeader />);
    const skip = screen.getAllByRole("link")[0];
    expect([skip.textContent, skip.getAttribute("href")]).toEqual(["Skip to content", "#content"]);
  });

  it("marks the current page, and the section of a page inside it", () => {
    pathname = "/authors";
    render(<SiteHeader />);
    expect(navLinks().map((a) => a.getAttribute("aria-current"))).toEqual([null, null, "page", null]);
    cleanup();
    pathname = "/works/kjv/gen";
    render(<SiteHeader />);
    expect(navLinks().map((a) => a.getAttribute("aria-current"))).toEqual([null, "location", null, null]);
  });
});

describe("isCurrent", () => {
  it("matches Search only on the landing page", () => {
    expect(isCurrent("/", "/")).toBe(true);
    expect(isCurrent("/", "/works")).toBe(false);
  });

  it("matches a section and its subpages, not a longer name", () => {
    expect(isCurrent("/works", "/works/oshb/gen")).toBe(true);
    expect(isCurrent("/authors", "/authorsx")).toBe(false);
  });
});
