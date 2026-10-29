import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import MachineTranslationNotice from "./MachineTranslationNotice";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));

afterEach(cleanup);

describe("MachineTranslationNotice", () => {
  it("names the original without a link when the library doesn't have it", () => {
    render(<MachineTranslationNotice />);
    const notice = screen.getByRole("note", { name: "Machine translation" });
    expect(notice.textContent).toContain("machine-translated from the original by an AI model");
    expect(screen.queryByRole("link")).toBeNull();
  });
});
