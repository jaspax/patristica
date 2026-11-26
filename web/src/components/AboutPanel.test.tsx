import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

let AboutPanel: typeof import("./AboutPanel").default;
const fetchMock = vi.fn();

beforeEach(async () => {
  vi.resetModules();
  AboutPanel = (await import("./AboutPanel")).default;
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  fetchMock.mockReset();
});

describe("AboutPanel", () => {
  it("shows the text and the Wikipedia link", async () => {
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ text: "A bishop of Hippo.", wikipedia: "https://en.wikipedia.org/wiki/Augustine_of_Hippo" })),
    );
    render(<AboutPanel file="about/authors/augustine-of-hippo.json" label="About Augustine" />);
    const aside = await screen.findByRole("complementary", { name: "About Augustine" });
    expect(aside.textContent).toContain("A bishop of Hippo.");
    expect(screen.getByRole("link", { name: "Wikipedia" }).getAttribute("href")).toBe(
      "https://en.wikipedia.org/wiki/Augustine_of_Hippo",
    );
    expect(aside.textContent).not.toContain("AI");
    expect(fetchMock.mock.calls[0][0]).toBe("/library/about/authors/augustine-of-hippo.json");
  });

  it("has no Wikipedia link without an article, and shows nothing when the load fails", async () => {
    fetchMock.mockResolvedValueOnce(new Response(JSON.stringify({ text: "A homily.", wikipedia: null })));
    render(<AboutPanel file="about/works/x/y.json" label="About this work" />);
    await screen.findByText("A homily.");
    expect(screen.queryByRole("link")).toBeNull();
    cleanup();

    fetchMock.mockResolvedValueOnce(new Response("", { status: 404 }));
    const { container } = render(<AboutPanel file="about/works/x/z.json" label="About this work" />);
    await new Promise((r) => setTimeout(r, 0));
    expect(container.textContent).toBe("");
  });
});
