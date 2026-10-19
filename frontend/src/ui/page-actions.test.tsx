import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import Button from "./Button.tsx";
import PageActions from "./PageActions.tsx";

afterEach(cleanup);

describe("PageActions", () => {
  it("groups the primary and the secondary action in the same keyboard order", () => {
    render(
      <PageActions
        label="Publish actions"
        sticky
        primary={<Button variant="primary">Schedule 3 posts</Button>}
        secondary={<Button variant="ghost">Finish later</Button>}
      />,
    );
    const group = screen.getByRole("group", { name: "Publish actions" });
    expect(
      within(group)
        .getAllByRole("button")
        .map((button) => button.textContent),
    ).toEqual(["Schedule 3 posts", "Finish later"]);
    // Stuck to the bottom on phones by CSS only: same DOM at every width.
    expect(group).toHaveClass("ap-page-actions--sticky");
  });
});
