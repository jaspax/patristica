import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";

import Home from "./page";

it("renders the home page heading", () => {
  render(<Home />);
  expect(screen.getByRole("heading", { level: 1, name: "Patristica" })).toBeDefined();
});
