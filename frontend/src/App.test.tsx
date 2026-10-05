import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App.tsx";
import { duplicateError, FakeApi } from "./test-fake-api.ts";

let api: FakeApi;

beforeEach(() => {
  api = new FakeApi();
  api.install();
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function projectList() {
  return screen.getByRole("list", { name: "Projects" });
}

describe("App", () => {
  it("renders the AutoPublisher heading", async () => {
    render(<App />);

    expect(
      screen.getByRole("heading", { name: "AutoPublisher" }),
    ).toBeInTheDocument();
    await screen.findByText(/No projects yet/);
  });

  it("shows an empty state when there are no projects", async () => {
    render(<App />);

    expect(
      await screen.findByText("No projects yet. Create your first project."),
    ).toBeInTheDocument();
  });

  it("creates a project and shows it in the list", async () => {
    const user = userEvent.setup();
    render(<App />);
    await screen.findByText(/No projects yet/);

    await user.type(screen.getByLabelText("Name"), "L4i4");
    await user.type(screen.getByLabelText("Description"), "Main brand");
    await user.click(screen.getByRole("button", { name: "Create project" }));

    expect(
      await within(projectList()).findByRole("button", { name: /L4i4/ }),
    ).toBeInTheDocument();
    expect(api.requests).toContainEqual({
      method: "POST",
      path: "/projects",
      body: { name: "L4i4", description: "Main brand" },
    });
    expect(
      await screen.findByRole("heading", { level: 2, name: "L4i4" }),
    ).toBeInTheDocument();
  });

  it("shows the details of the selected project", async () => {
    api.addProject({ name: "L4i4", description: "Main brand" });
    api.addProject({ name: "Cybersecurity", is_active: false });
    const user = userEvent.setup();
    render(<App />);

    await user.click(
      await within(projectList()).findByRole("button", {
        name: /Cybersecurity/,
      }),
    );

    const detail = await screen.findByRole("region", { name: "Cybersecurity" });
    expect(within(detail).getByText("Inactive")).toBeInTheDocument();
    expect(within(detail).getByText("No description")).toBeInTheDocument();
    expect(within(detail).getByText(/Created/)).toBeInTheDocument();
    expect(within(detail).getByText(/Last updated/)).toBeInTheDocument();
  });

  it("marks inactive projects in the list", async () => {
    api.addProject({ name: "Cybersecurity", is_active: false });
    render(<App />);

    const item = await within(projectList()).findByRole("button", {
      name: /Cybersecurity/,
    });
    expect(within(item).getByText("Inactive")).toBeInTheDocument();
  });

  it("shows a duplicate name error and keeps the typed values", async () => {
    api.addProject({ name: "L4i4" });
    api.failNext(
      409,
      duplicateError("name", "A project with this name already exists."),
    );
    const user = userEvent.setup();
    render(<App />);
    await within(projectList()).findByRole("button", { name: /L4i4/ });

    await user.type(screen.getByLabelText("Name"), "l4i4");
    await user.click(screen.getByRole("button", { name: "Create project" }));

    expect(
      await screen.findByText("A project with this name already exists."),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Name")).toHaveValue("l4i4");
  });

  it("shows an error when the server cannot be reached", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("failed")));
    render(<App />);

    expect(
      await screen.findByText("Could not reach the server."),
    ).toBeInTheDocument();
  });

  it("edits the selected project", async () => {
    api.addProject({ name: "L4i4", description: "Art" });
    const user = userEvent.setup();
    render(<App />);
    await user.click(
      await within(projectList()).findByRole("button", { name: /L4i4/ }),
    );

    await user.click(screen.getByRole("button", { name: "Edit project" }));
    const form = screen.getByRole("form", { name: "Edit project" });
    expect(within(form).getByLabelText("Name")).toHaveValue("L4i4");
    await user.clear(within(form).getByLabelText("Name"));
    await user.type(within(form).getByLabelText("Name"), "L4i4 Studio");
    await user.click(within(form).getByRole("button", { name: "Save" }));

    expect(
      await screen.findByRole("heading", { level: 2, name: "L4i4 Studio" }),
    ).toBeInTheDocument();
    expect(api.requests).toContainEqual({
      method: "PATCH",
      path: "/projects/1",
      body: { name: "L4i4 Studio", description: "Art" },
    });
  });

  it("deactivates and reactivates the selected project", async () => {
    api.addProject({ name: "Cybersecurity" });
    const user = userEvent.setup();
    render(<App />);
    await user.click(
      await within(projectList()).findByRole("button", {
        name: /Cybersecurity/,
      }),
    );
    await screen.findByRole("form", { name: "Add account" });

    await user.click(
      screen.getByRole("button", { name: "Deactivate project" }),
    );

    const listItem = await within(projectList()).findByRole("button", {
      name: /Cybersecurity.*Inactive/,
    });
    expect(listItem).toBeInTheDocument();
    expect(
      screen.getByText("Reactivate this project to add accounts."),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("form", { name: "Add account" }),
    ).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Activate project" }));

    expect(
      await screen.findByRole("form", { name: "Add account" }),
    ).toBeInTheDocument();
    expect(
      within(projectList()).getByRole("button", { name: "Cybersecurity" }),
    ).toBeInTheDocument();
    expect(api.requests.filter((r) => r.method === "PATCH")).toEqual([
      { method: "PATCH", path: "/projects/1", body: { is_active: false } },
      { method: "PATCH", path: "/projects/1", body: { is_active: true } },
    ]);
  });
});
