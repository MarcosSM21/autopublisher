import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { duplicateError, FakeApi } from "../test-fake-api.ts";
import type { Project } from "../types.ts";
import ProjectDetail from "./ProjectDetail.tsx";

let api: FakeApi;
let project: Project;

beforeEach(() => {
  api = new FakeApi();
  api.install();
  project = api.addProject({ name: "L4i4" });
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function renderDetail(selected: Project = project) {
  return render(
    <ProjectDetail project={selected} onProjectChanged={vi.fn()} />,
  );
}

function accountList() {
  return screen.getByRole("list", { name: "Accounts" });
}

function addAccountForm() {
  return screen.getByRole("form", { name: "Add account" });
}

describe("ProjectDetail accounts", () => {
  it("lists the accounts of the project with their status", async () => {
    api.addAccount({
      project_id: project.id,
      platform: "instagram",
      handle: "l4i4",
      display_name: "L4i4 Official",
    });
    api.addAccount({
      project_id: project.id,
      platform: "x",
      handle: "l4i4",
      is_active: false,
    });
    renderDetail();

    const list = await screen.findByRole("list", { name: "Accounts" });
    const items = within(list).getAllByRole("listitem");
    expect(items).toHaveLength(2);
    expect(within(items[0]).getByText("@l4i4")).toBeInTheDocument();
    expect(within(items[0]).getByText("Instagram")).toBeInTheDocument();
    expect(within(items[0]).getByText("L4i4 Official")).toBeInTheDocument();
    expect(within(items[0]).getByText("Active")).toBeInTheDocument();
    expect(within(items[1]).getByText("X")).toBeInTheDocument();
    expect(within(items[1]).getByText("Inactive")).toBeInTheDocument();
  });

  it("shows an empty state when the project has no accounts", async () => {
    renderDetail();

    expect(await screen.findByText("No accounts yet.")).toBeInTheDocument();
  });

  it("offers exactly the six recognised platforms", async () => {
    renderDetail();
    await screen.findByText("No accounts yet.");

    const select = within(addAccountForm()).getByLabelText("Platform");
    const options = within(select)
      .getAllByRole("option")
      .map((option) => option.textContent)
      .filter((label) => label !== "Select a platform");

    expect(options).toEqual([
      "YouTube",
      "Instagram",
      "TikTok",
      "X",
      "Threads",
      "Telegram",
    ]);
  });

  it("adds an account and shows it in the list", async () => {
    const user = userEvent.setup();
    renderDetail();
    await screen.findByText("No accounts yet.");
    const form = addAccountForm();

    await user.selectOptions(within(form).getByLabelText("Platform"), "tiktok");
    await user.type(within(form).getByLabelText("Handle"), "@l4i4");
    await user.type(within(form).getByLabelText("Display name"), "L4i4");
    await user.click(within(form).getByRole("button", { name: "Add account" }));

    expect(
      await within(accountList()).findByText("TikTok"),
    ).toBeInTheDocument();
    expect(within(accountList()).getByText("@l4i4")).toBeInTheDocument();
    expect(api.requests).toContainEqual({
      method: "POST",
      path: `/projects/${project.id}/accounts`,
      body: { platform: "tiktok", handle: "@l4i4", display_name: "L4i4" },
    });
  });

  it("shows a duplicate error next to the handle and keeps the values", async () => {
    api.failNext(
      409,
      duplicateError("handle", "This project already has this account."),
    );
    const user = userEvent.setup();
    renderDetail();
    await screen.findByText("No accounts yet.");
    const form = addAccountForm();

    await user.selectOptions(
      within(form).getByLabelText("Platform"),
      "instagram",
    );
    await user.type(within(form).getByLabelText("Handle"), "l4i4");
    await user.click(within(form).getByRole("button", { name: "Add account" }));

    expect(
      await within(form).findByText("This project already has this account."),
    ).toBeInTheDocument();
    expect(within(form).getByLabelText("Handle")).toHaveValue("l4i4");
    expect(within(form).getByLabelText("Platform")).toHaveValue("instagram");
  });

  it("edits an account keeping its platform read-only", async () => {
    const account = api.addAccount({
      project_id: project.id,
      platform: "instagram",
      handle: "l4i4",
    });
    const user = userEvent.setup();
    renderDetail();
    const list = await screen.findByRole("list", { name: "Accounts" });

    await user.click(within(list).getByRole("button", { name: "Edit" }));
    const form = screen.getByRole("form", { name: "Edit account" });
    expect(within(form).getByLabelText("Platform")).toHaveValue("Instagram");
    expect(within(form).getByLabelText("Platform")).toHaveAttribute("readonly");
    await user.clear(within(form).getByLabelText("Handle"));
    await user.type(within(form).getByLabelText("Handle"), "l4i4_art");
    await user.type(within(form).getByLabelText("Display name"), "Art");
    await user.click(within(form).getByRole("button", { name: "Save" }));

    expect(
      await within(accountList()).findByText("@l4i4_art"),
    ).toBeInTheDocument();
    expect(api.requests).toContainEqual({
      method: "PATCH",
      path: `/accounts/${account.id}`,
      body: { handle: "l4i4_art", display_name: "Art" },
    });
  });

  it("deactivates and reactivates an account", async () => {
    api.addAccount({ project_id: project.id, platform: "x", handle: "l4i4" });
    const user = userEvent.setup();
    renderDetail();
    const list = await screen.findByRole("list", { name: "Accounts" });

    await user.click(within(list).getByRole("button", { name: "Deactivate" }));
    expect(
      await within(accountList()).findByText("Inactive"),
    ).toBeInTheDocument();

    await user.click(
      within(accountList()).getByRole("button", { name: "Activate" }),
    );
    expect(
      await within(accountList()).findByText("Active"),
    ).toBeInTheDocument();
    expect(within(accountList()).getByRole("listitem")).toBeInTheDocument();
  });

  it("shows an edit error inline and keeps the typed values", async () => {
    api.addAccount({
      project_id: project.id,
      platform: "instagram",
      handle: "l4i4",
    });
    api.failNext(
      409,
      duplicateError("handle", "This project already has this account."),
    );
    const user = userEvent.setup();
    renderDetail();
    const list = await screen.findByRole("list", { name: "Accounts" });

    await user.click(within(list).getByRole("button", { name: "Edit" }));
    const form = screen.getByRole("form", { name: "Edit account" });
    await user.clear(within(form).getByLabelText("Handle"));
    await user.type(within(form).getByLabelText("Handle"), "taken");
    await user.click(within(form).getByRole("button", { name: "Save" }));

    expect(
      await within(form).findByText("This project already has this account."),
    ).toBeInTheDocument();
    expect(within(form).getByLabelText("Handle")).toHaveValue("taken");
  });

  it("asks for a platform without exposing internal values", async () => {
    const user = userEvent.setup();
    renderDetail();
    await screen.findByText("No accounts yet.");
    const form = addAccountForm();

    await user.type(within(form).getByLabelText("Handle"), "l4i4");
    await user.click(within(form).getByRole("button", { name: "Add account" }));

    expect(
      await within(form).findByText("Select a platform."),
    ).toBeInTheDocument();
    expect(within(form).queryByText(/youtube/)).not.toBeInTheDocument();
    expect(within(form).getByLabelText("Handle")).toHaveValue("l4i4");
    expect(api.requests.filter((r) => r.method === "POST")).toEqual([]);
  });
});
