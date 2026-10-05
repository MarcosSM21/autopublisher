import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import App from "./App.tsx";

afterEach(() => {
  cleanup();
});

describe("App", () => {
  it("renders the AutoPublisher heading", () => {
    render(<App />);

    expect(
      screen.getByRole("heading", { name: "AutoPublisher" }),
    ).toBeInTheDocument();
  });
});
