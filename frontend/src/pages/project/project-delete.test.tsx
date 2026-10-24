import { cleanup, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { FakeApi } from "../../test-fake-api.ts";
import { renderRoute } from "../../test-utils.tsx";
import type { Project } from "../../types.ts";

const LAST_PROJECT_KEY = "autopublisher.lastProjectId";

let api: FakeApi;
let project: Project;

beforeEach(() => {
  api = new FakeApi();
  api.install();
  project = api.addProject({ name: "L4i4" });
});

afterEach(() => {
  window.localStorage.clear();
  cleanup();
  vi.unstubAllGlobals();
});

async function deleteProject(path: string) {
  const user = userEvent.setup();
  const view = renderRoute(path);
  await user.click(
    await screen.findByRole("button", { name: "Project actions" }),
  );
  await user.click(screen.getByRole("button", { name: "Delete project" }));
  const dialog = screen.getByRole("dialog", { name: "Delete project?" });
  const confirm = await within(dialog).findByRole("button", { name: "Delete" });
  return { user, dialog, confirm, ...view };
}

function selectorOptions() {
  return within(screen.getByRole("combobox", { name: "Project" }))
    .getAllByRole("option")
    .map((option) => option.textContent);
}

describe("Delete project", () => {
  it("summarises its content, then Home without it in the selector", async () => {
    api.addProject({ name: "Other" });
    const account = api.addAccount({
      project_id: project.id,
      platform: "youtube",
      handle: "chan",
    });
    const media = api.addContent({ project_id: project.id, title: "Clip" });
    api.addPublication({ content_id: media.id, account_id: account.id });

    // Deep inside the project: a Post detail.
    const { user, dialog, confirm, router } = await deleteProject(
      `/p/${project.id}/posts/${api.publications[0].id}`,
    );
    expect(dialog).toHaveTextContent(
      "This project contains 1 account, 1 post and 1 media item. Everything will be removed from AutoPublisher.",
    );
    expect(within(dialog).queryByRole("textbox")).toBeNull();
    expect(window.localStorage.getItem(LAST_PROJECT_KEY)).toBe(
      String(project.id),
    );
    await user.click(confirm);

    expect(router.state.location.pathname).toBe("/");
    expect(await screen.findByText("Project deleted.")).toBeInTheDocument();
    await vi.waitFor(() => expect(selectorOptions()).toEqual(["Other"]));
    expect(screen.queryByText("L4i4")).toBeNull();
    // Nothing remembers the deleted id.
    expect(window.localStorage.getItem(LAST_PROJECT_KEY)).toBeNull();
    expect(api.contents).toHaveLength(0);
    expect(api.accounts).toHaveLength(0);
  });

  it("the last project ends in the existing empty onboarding", async () => {
    const { user, confirm, router } = await deleteProject(
      `/p/${project.id}/library`,
    );
    await user.click(confirm);

    expect(router.state.location.pathname).toBe("/");
    expect(
      await screen.findByRole("heading", { name: "Create your first project" }),
    ).toBeInTheDocument();
    expect(screen.getByText("No projects yet")).toBeInTheDocument();
  });

  it("is a secondary item of Project actions", async () => {
    const user = userEvent.setup();
    renderRoute(`/p/${project.id}/library`);
    await user.click(
      await screen.findByRole("button", { name: "Project actions" }),
    );
    const button = screen.getByRole("button", { name: "Delete project" });
    expect(button).toHaveClass("ap-button--secondary", "ap-delete-entry");
  });
});
