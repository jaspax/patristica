import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { WorkRow } from "@/lib/library";
import { workRow } from "@/lib/testFixtures";
import { originalIds } from "@/lib/versions";

import VersionSwitcher, { FloatingVersions } from "./VersionSwitcher";

const push = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push }),
}));

const sources = {
  oshb: "Open Scriptures Hebrew Bible",
  "lxx-rahlfs": "Septuagint (Rahlfs)",
  "pta-lxx": "Septuagint (Patristic Text Archive)",
  clementine: "Clementine Vulgate",
  kjv: "King James Version",
  web: "World English Bible",
  first1k: "First Thousand Years of Greek",
  "anf-works": "Ante-Nicene Fathers",
};

const book = (source: string, language: string, overrides: Partial<WorkRow> = {}) =>
  workRow({
    id: `${source}/ps`,
    source_id: source,
    language,
    title: "Psalms",
    genre: "scripture",
    license: "public_domain",
    version_group: "book:ps",
    ...overrides,
  });

const psalms = [
  book("oshb", "hbo", { license: "cc-by-4.0", edition: "Open Scriptures Hebrew Bible (morphhb), Westminster Leningrad Codex" }),
  book("lxx-rahlfs", "grc"),
  book("pta-lxx", "grc", { title: "Psalms (LXX)" }),
  book("clementine", "lat"),
  book("kjv", "eng"),
  book("web", "eng"),
];
const kjv = psalms[4];

beforeEach(() => push.mockClear());
afterEach(cleanup);

function renderPsalms(positionFor?: (w: WorkRow) => Promise<string | null>) {
  return render(
    <VersionSwitcher
      current={kjv}
      members={psalms}
      originals={originalIds(psalms)}
      sources={sources}
      positionFor={positionFor}
    />,
  );
}

describe("VersionSwitcher", () => {
  it("lists every other version under language headings, the original first", () => {
    renderPsalms();
    expect(screen.getByText("Other versions (5 in 4 languages)")).toBeDefined();
    const lists = screen.getAllByRole("list");
    expect(lists.map((l) => l.getAttribute("aria-labelledby") && document.getElementById(l.getAttribute("aria-labelledby")!)?.textContent)).toEqual(
      ["Hebrew", "English", "Greek", "Latin"],
    );
    const hebrew = within(lists[0]).getByRole("link", { name: "Open Scriptures Hebrew Bible" });
    expect(hebrew.getAttribute("href")).toBe("/works/oshb/ps");
    expect(within(lists[0]).getByText("Original")).toBeDefined();
    // The work being read is not listed.
    expect(within(lists[1]).getAllByRole("link").map((a) => a.textContent)).toEqual(["World English Bible"]);
  });

  it("keeps entries short: the title only where it differs, no edition or licence", () => {
    renderPsalms();
    const pta = screen.getByRole("link", { name: "Septuagint (Patristic Text Archive)" });
    const facts = document.getElementById(pta.getAttribute("aria-describedby")!)!;
    expect(facts.textContent).toBe("Psalms (LXX)");
    expect(facts.querySelector("[lang=grc]")?.textContent).toBe("Psalms (LXX)");
    // Grouped by language, a version with the same title has nothing to add.
    const oshb = screen.getByRole("link", { name: "Open Scriptures Hebrew Bible" });
    expect(oshb.getAttribute("aria-describedby")).toBeNull();
    expect(oshb.closest("li")!.textContent).toBe("Open Scriptures Hebrew BibleOriginal");
    expect(document.body.textContent).not.toContain("Westminster Leningrad Codex");
    expect(document.body.textContent).not.toMatch(/Public domain|CC BY/);
  });

  it("adds the edition only to versions that would otherwise look the same", () => {
    const grc = workRow({ id: "first1k/a", language: "grc", source_id: "first1k", title: "Epistula", version_group: "g" });
    const anf1 = workRow({ id: "anf-works/a", language: "eng", source_id: "anf-works", title: "Epistle", edition: "ANF Vol. 1", translation_of: "first1k/a", version_group: "g" });
    const anf9 = workRow({ id: "anf-works/a9", language: "eng", source_id: "anf-works", title: "Epistle", edition: "ANF Vol. 9", translation_of: "first1k/a", version_group: "g" });
    render(<VersionSwitcher current={grc} members={[grc, anf1, anf9]} originals={originalIds([grc, anf1, anf9])} sources={sources} />);
    const items = screen.getAllByRole("listitem").map((li) => li.textContent);
    expect(items).toEqual([
      "Ante-Nicene FathersEnglish · , Epistle · , ANF Vol. 1",
      "Ante-Nicene FathersEnglish · , Epistle · , ANF Vol. 9",
    ]);
  });

  it("lists a short group without headings, naming each language", () => {
    const grc = workRow({ id: "first1k/a", language: "grc", source_id: "first1k", title: "Epistula", edition: "1st1K-grc1", version_group: "g" });
    const eng = workRow({ id: "anf-works/a", language: "eng", source_id: "anf-works", title: "Epistle", translation_of: "first1k/a", version_group: "g" });
    render(<VersionSwitcher current={eng} members={[grc, eng]} originals={originalIds([grc, eng])} sources={sources} />);
    expect(screen.getByText("Other versions (1)")).toBeDefined();
    const link = screen.getByRole("link", { name: "First Thousand Years of Greek" });
    const facts = document.getElementById(link.getAttribute("aria-describedby")!)!.textContent;
    expect(facts).toContain("Greek");
    expect(facts).toContain("Epistula");
    // Editions are left out when the entries differ anyway.
    expect(facts).not.toContain("1st1K-grc1");
    expect(screen.getByText("Original")).toBeDefined();
  });

  it("renders nothing for a work with no other version", () => {
    const { container } = render(
      <VersionSwitcher current={kjv} members={[]} originals={new Set()} sources={sources} />,
    );
    expect(container.innerHTML).toBe("");
  });

  it("opens the other version at the passage positionFor finds", async () => {
    const positionFor = vi.fn(async () => "Ps.22.1");
    renderPsalms(positionFor);
    fireEvent.click(screen.getByRole("link", { name: "Clementine Vulgate" }));
    await waitFor(() => expect(push).toHaveBeenCalledWith("/works/clementine/ps#Ps.22.1"));
    expect(positionFor).toHaveBeenCalledWith(psalms[3]);
  });

  it("opens at the top when there is no passage or the lookup fails", async () => {
    renderPsalms(async () => null);
    fireEvent.click(screen.getByRole("link", { name: "Clementine Vulgate" }));
    await waitFor(() => expect(push).toHaveBeenCalledWith("/works/clementine/ps"));
    cleanup();
    push.mockClear();
    renderPsalms(async () => {
      throw new Error("offline");
    });
    fireEvent.click(screen.getByRole("link", { name: "Clementine Vulgate" }));
    await waitFor(() => expect(push).toHaveBeenCalledWith("/works/clementine/ps"));
  });

  it("leaves modified clicks (new tab) to the browser", () => {
    const positionFor = vi.fn(async () => "Ps.22.1");
    renderPsalms(positionFor);
    // jsdom can't open a tab: stop the browser's default action after the component's handler.
    const stop = (e: Event) => e.preventDefault();
    window.addEventListener("click", stop);
    fireEvent.click(screen.getByRole("link", { name: "Clementine Vulgate" }), { ctrlKey: true });
    window.removeEventListener("click", stop);
    expect(positionFor).not.toHaveBeenCalled();
    expect(push).not.toHaveBeenCalled();
  });
});

describe("FloatingVersions", () => {
  function renderFloating(visible: boolean, positionFor?: (w: WorkRow) => Promise<string | null>) {
    return render(
      <div>
        <p>
          <a href="#Ps.1.1">1</a>
        </p>
        <FloatingVersions
          visible={visible}
          current={kjv}
          members={psalms}
          originals={originalIds(psalms)}
          sources={sources}
          positionFor={positionFor}
        />
      </div>,
    );
  }

  it("is absent while the header's list is on screen", () => {
    renderFloating(false);
    expect(screen.queryByRole("button", { name: /Other versions/ })).toBeNull();
  });

  it("opens a list of the versions and moves focus into it", () => {
    renderFloating(true);
    const button = screen.getByRole("button", { name: "Other versions (5 in 4 languages)" });
    expect(button.getAttribute("aria-expanded")).toBe("false");
    expect(screen.queryByRole("dialog")).toBeNull();
    fireEvent.click(button);
    expect(button.getAttribute("aria-expanded")).toBe("true");
    const dialog = screen.getByRole("dialog", { name: "Other versions" });
    expect(button.getAttribute("aria-controls")).toBe(dialog.id);
    expect(document.activeElement).toBe(within(dialog).getByRole("link", { name: "Open Scriptures Hebrew Bible" }));
  });

  it("closes on Escape and returns focus to the button", () => {
    renderFloating(true);
    const button = screen.getByRole("button", { name: /Other versions/ });
    fireEvent.click(button);
    fireEvent.keyDown(document.activeElement!, { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(button.getAttribute("aria-expanded")).toBe("false");
    expect(document.activeElement).toBe(button);
  });

  it("closes on a click outside, and toggles from its button", () => {
    renderFloating(true);
    const button = screen.getByRole("button", { name: /Other versions/ });
    fireEvent.click(button);
    fireEvent.pointerDown(screen.getByRole("link", { name: "1" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    fireEvent.click(button);
    fireEvent.pointerDown(within(screen.getByRole("dialog")).getAllByRole("link")[0]);
    expect(screen.getByRole("dialog")).toBeDefined();
    fireEvent.click(button);
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("stays open while in use when the header comes back into view", () => {
    const floating = (visible: boolean) => (
      <FloatingVersions visible={visible} current={kjv} members={psalms} originals={originalIds(psalms)} sources={sources} />
    );
    const { rerender } = render(floating(true));
    fireEvent.click(screen.getByRole("button", { name: /Other versions/ }));
    rerender(floating(false));
    expect(screen.getByRole("dialog")).toBeDefined();
    // Closed, it goes away with the header in view.
    fireEvent.keyDown(document.body, { key: "Escape" });
    expect(screen.queryByRole("button", { name: /Other versions/ })).toBeNull();
  });

  it("switches at the passage being read when a version is chosen", async () => {
    const positionFor = vi.fn(async () => "Ps.22.1");
    renderFloating(true, positionFor);
    fireEvent.click(screen.getByRole("button", { name: /Other versions/ }));
    fireEvent.click(screen.getByRole("link", { name: "Clementine Vulgate" }));
    await waitFor(() => expect(push).toHaveBeenCalledWith("/works/clementine/ps#Ps.22.1"));
  });
});
