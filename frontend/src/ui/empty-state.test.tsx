import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, describe, expect, it } from "vitest";
import Button from "./Button.tsx";
import EmptyState from "./EmptyState.tsx";

afterEach(cleanup);

function renderEmpty(icon?: "folder") {
  return render(
    <MemoryRouter>
      <EmptyState
        title="No media yet"
        description="Import photos or videos to start."
        action={<Button variant="primary">Import media</Button>}
        secondary={{ to: "/help", label: "How it works" }}
        icon={icon}
      />
    </MemoryRouter>,
  );
}

describe("EmptyState", () => {
  it("keeps title, description and the single action with an icon", () => {
    const { container } = renderEmpty("folder");
    expect(
      screen.getByRole("heading", { level: 2, name: "No media yet" }),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Import photos or videos to start."),
    ).toBeInTheDocument();
    expect(screen.getAllByRole("button")).toHaveLength(1);
    expect(screen.getByRole("link", { name: "How it works" })).toBeVisible();
    // The icon is decorative: hidden from assistive technology.
    const icon = container.querySelector(".ap-empty__icon");
    expect(icon).toHaveAttribute("aria-hidden", "true");
  });

  it("renders no icon wrapper without the prop", () => {
    const { container } = renderEmpty();
    expect(container.querySelector(".ap-empty__icon")).toBeNull();
    expect(container.querySelector("svg")).toBeNull();
    expect(screen.getAllByRole("button")).toHaveLength(1);
  });
});
