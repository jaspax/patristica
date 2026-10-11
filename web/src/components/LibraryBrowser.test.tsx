import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { LibraryIndex, WorkRow } from "@/lib/library";

const replace = vi.fn();
let search = "";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace }),
  usePathname: () => "/",
  useSearchParams: () => new URLSearchParams(search),
}));

function row(overrides: Partial<WorkRow>): WorkRow {
  return {
    id: "x",
    author: null,
    title: "Untitled",
    language: "lat",
    genre: "patristic",
    tradition: null,
    date: null,
    date_range: null,
    date_confidence: "uncertain",
    source_id: "patristic/pta",
    edition: null,
    license: "unknown",
    provenance_url: null,
    translation_of: null,
    chunks: 1,
    file: "works/x.json",
    ...overrides,
  };
}

const index: LibraryIndex = {
  built_at: "2026-10-11T00:00:00Z",
  sources: { "patristic/pta": "Patristic Text Archive" },
  works: [
    row({ id: "aug/conf", author: "Augustinus", title: "Confessiones", date: 397 }),
    row({ id: "bas/ep", author: "Basilius", title: "Epistulae", language: "grc", date: 370 }),
  ],
};

// lib/library caches the index per page session; reload the modules for each test.
let LibraryBrowser: typeof import("./LibraryBrowser").default;

beforeEach(async () => {
  vi.resetModules();
  LibraryBrowser = (await import("./LibraryBrowser")).default;
  search = "";
  replace.mockClear();
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response(JSON.stringify(index))),
  );
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("LibraryBrowser", () => {
  it("lists every work with links to the reader", async () => {
    render(<LibraryBrowser />);
    expect(await screen.findByText("2 works")).toBeDefined();
    const link = screen.getByRole("link", { name: "Confessiones" });
    expect(link.getAttribute("href")).toBe("/works/aug/conf");
  });

  it("applies the filters from the URL", async () => {
    search = "language=grc";
    render(<LibraryBrowser />);
    expect(await screen.findByText(/1 of 2 works/)).toBeDefined();
    expect(screen.queryByText("Confessiones")).toBeNull();
    expect(screen.getByText("Epistulae")).toBeDefined();
  });

  it("writes searches and sorting to the URL", async () => {
    render(<LibraryBrowser />);
    fireEvent.change(await screen.findByRole("searchbox"), { target: { value: "basil" } });
    expect(replace).toHaveBeenLastCalledWith("/?q=basil", { scroll: false });

    fireEvent.click(screen.getByRole("button", { name: /Date/ }));
    expect(replace).toHaveBeenLastCalledWith("/?sort=date", { scroll: false });
  });

  it("explains how to export the library when it is missing", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("", { status: 404, statusText: "Not Found" })));
    render(<LibraryBrowser />);
    expect(await screen.findByRole("alert")).toBeDefined();
    expect(screen.getByText(/export_library/)).toBeDefined();
  });
});
