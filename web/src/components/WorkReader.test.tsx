import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { AuthorsFile, LibraryIndex, WorkFile } from "@/lib/library";
import { person, workRow } from "@/lib/testFixtures";

let params: { id: string[] } = { id: ["pl", "both"] };

vi.mock("next/navigation", () => ({
  useParams: () => params,
}));

const index: LibraryIndex = {
  version: "0123456789abcdef",
  sources: { pl: "Patrologia Latina" },
  works: [
    workRow({
      id: "pl/both",
      author: "Hieronymus; Augustinus",
      author_ids: ["jerome", "augustine-of-hippo"],
      title: "Epistulae mutuae",
      source_id: "pl",
      file: "works/pl/both.json",
    }),
    workRow({ id: "pl/acta", author: "Acta Thomae", title: "Acta Thomae", source_id: "pl", file: "works/pl/acta.json" }),
  ],
};

const authors: AuthorsFile = {
  authors: [
    person({ id: "jerome", name: "Jerome", aliases: ["Hieronymus"] }),
    person({ id: "augustine-of-hippo", name: "Augustine of Hippo", aliases: ["Augustinus"] }),
  ],
};

const work: WorkFile = { work_id: "pl/both", ref_prefix: "Ep", chunks: [["1", "Salve."]] };

let WorkReader: typeof import("./WorkReader").default;

beforeEach(async () => {
  vi.resetModules();
  WorkReader = (await import("./WorkReader")).default;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      const body = url.endsWith("/authors.json") ? authors : url.endsWith("/index.json") ? index : work;
      return new Response(JSON.stringify(body));
    }),
  );
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("WorkReader author line", () => {
  it("links each author to its author page and keeps the source's attribution", async () => {
    params = { id: ["pl", "both"] };
    render(<WorkReader />);
    const jerome = await screen.findByRole("link", { name: "Jerome" });
    expect(jerome.getAttribute("href")).toBe("/authors/jerome");
    const augustine = screen.getByRole("link", { name: "Augustine of Hippo" });
    expect(augustine.getAttribute("href")).toBe("/authors/augustine-of-hippo");
    expect(screen.getByText("Attributed as")).toBeDefined();
    expect(screen.getByText("Hieronymus; Augustinus")).toBeDefined();
  });

  it("shows no author link for an anonymous work", async () => {
    params = { id: ["pl", "acta"] };
    render(<WorkReader />);
    await screen.findByRole("heading", { level: 1, name: "Acta Thomae" });
    expect(screen.queryAllByRole("link").filter((a) => a.getAttribute("href")?.startsWith("/authors/"))).toEqual(
      [],
    );
  });
});
