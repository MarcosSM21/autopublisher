import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { FakeApi } from "../test-fake-api.ts";
import type { Account, Project } from "../types.ts";
import ProjectDetail from "./ProjectDetail.tsx";

let api: FakeApi;
let project: Project;
let threads: Account;

beforeEach(() => {
  api = new FakeApi();
  api.install();
  project = api.addProject({ name: "Cyber" });
  threads = api.addAccount({
    project_id: project.id,
    platform: "threads",
    handle: "cyberstudio",
  });
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

async function openForm() {
  const user = userEvent.setup();
  render(<ProjectDetail project={project} onProjectChanged={vi.fn()} />);
  await user.click(screen.getByRole("button", { name: "Queue" }));
  await user.click(
    await screen.findByRole("button", { name: "New text post" }),
  );
  return user;
}

function form() {
  return screen.getByRole("form", { name: "New text post" });
}

function creations() {
  return api.requests.filter(
    (request) =>
      request.method === "POST" && request.path.endsWith("/text-publications"),
  );
}

describe("new text post", () => {
  it("only offers active accounts of text post platforms", async () => {
    const second = api.addAccount({
      project_id: project.id,
      platform: "threads",
      handle: "second",
    });
    api.addAccount({
      project_id: project.id,
      platform: "threads",
      handle: "inactive",
      is_active: false,
    });
    api.addAccount({
      project_id: project.id,
      platform: "instagram",
      handle: "insta",
    });
    api.addAccount({
      project_id: project.id,
      platform: "youtube",
      handle: "tube",
    });

    await openForm();

    const boxes = within(form()).getAllByRole("checkbox");
    expect(
      boxes.map((box) => box.closest("label")?.textContent?.trim()),
    ).toEqual(["Threads @cyberstudio", `Threads @${second.handle}`]);
  });

  it("creates a text post with its text, hashtags and account", async () => {
    const user = await openForm();

    await user.type(
      within(form()).getByLabelText("Text"),
      "Hello Threads 🚀 https://example.com",
    );
    await user.type(
      within(form()).getByLabelText("Hashtags (optional)"),
      "#cyber, studio",
    );
    await user.click(
      within(form()).getByRole("button", { name: "Create text post" }),
    );

    expect(creations()).toEqual([
      {
        method: "POST",
        path: `/projects/${project.id}/text-publications`,
        body: {
          account_ids: [threads.id],
          description: "Hello Threads 🚀 https://example.com",
          hashtags: ["#cyber", "studio"],
        },
      },
    ]);
    expect(await screen.findByText("Created 1 text post.")).toBeInTheDocument();
    const unscheduled = screen.getByRole("list", {
      name: "Unscheduled publications",
    });
    expect(within(unscheduled).getByText("Text post")).toBeInTheDocument();
    expect(
      within(unscheduled).getByText("Hello Threads 🚀 https://example.com"),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("form", { name: "New text post" }),
    ).not.toBeInTheDocument();
  });

  it("schedules with explicit auto-publish consent", async () => {
    const user = await openForm();

    await user.type(within(form()).getByLabelText("Text"), "Scheduled");
    await user.type(
      within(form()).getByLabelText("Publish at (optional)"),
      "2100-01-01T10:00",
    );
    expect(
      within(form()).getByRole("button", { name: "Create text post" }),
    ).toBeInTheDocument();
    await user.click(
      within(form()).getByRole("checkbox", {
        name: "Publish automatically at this time",
      }),
    );
    await user.click(
      within(form()).getByRole("button", {
        name: "Schedule & enable auto-publish",
      }),
    );

    const [request] = creations();
    expect(request.body).toMatchObject({
      account_ids: [threads.id],
      description: "Scheduled",
      hashtags: [],
      auto_publish_enabled: true,
    });
    expect((request.body as { scheduled_at: string }).scheduled_at).toMatch(
      /^2100-01-01T/,
    );
  });

  it("never enables auto-publish without the explicit choice", async () => {
    const user = await openForm();

    await user.type(within(form()).getByLabelText("Text"), "Scheduled");
    await user.type(
      within(form()).getByLabelText("Publish at (optional)"),
      "2100-01-01T10:00",
    );
    await user.click(
      within(form()).getByRole("button", { name: "Create text post" }),
    );

    expect(creations()[0].body).toMatchObject({ auto_publish_enabled: false });
  });

  it("shows the per-account errors of the API", async () => {
    api.failNext(422, {
      error: {
        code: "text_publication_not_supported",
        message: "Some accounts cannot publish posts without media.",
        fields: [
          {
            field: "account_ids",
            message: "Threads @cyberstudio cannot publish posts without media.",
          },
        ],
      },
    });
    const user = await openForm();

    await user.type(within(form()).getByLabelText("Text"), "Hello");
    await user.click(
      within(form()).getByRole("button", { name: "Create text post" }),
    );

    const alert = await within(form()).findByRole("alert");
    expect(alert).toHaveTextContent(
      "Some accounts cannot publish posts without media.",
    );
    expect(alert).toHaveTextContent(
      "Threads @cyberstudio cannot publish posts without media.",
    );
    expect(within(form()).getByLabelText("Text")).toHaveValue("Hello");
  });

  it("can be cancelled without creating anything", async () => {
    const user = await openForm();

    await user.click(within(form()).getByRole("button", { name: "Cancel" }));

    expect(
      screen.queryByRole("form", { name: "New text post" }),
    ).not.toBeInTheDocument();
    expect(creations()).toEqual([]);
  });
});

describe("text post details", () => {
  it("shows the text and publishes it now", async () => {
    const publication = api.addPublication({
      content_id: null,
      account_id: threads.id,
      description_override: "Hello Threads",
      hashtags_override: ["cyber"],
    });
    const user = userEvent.setup();
    render(<ProjectDetail project={project} onProjectChanged={vi.fn()} />);
    await user.click(screen.getByRole("button", { name: "Queue" }));
    await user.click(
      await screen.findByRole("button", { name: /Hello Threads/ }),
    );

    const details = screen.getByRole("region", { name: "Publication details" });
    expect(
      within(details).getByRole("heading", { name: "Hello Threads" }),
    ).toBeInTheDocument();
    expect(within(details).getAllByText("Text post").length).toBeGreaterThan(0);
    expect(within(details).queryByRole("img")).not.toBeInTheDocument();
    expect(
      within(details).queryByText("Using content value"),
    ).not.toBeInTheDocument();
    expect(within(details).queryByLabelText(/Title/)).not.toBeInTheDocument();
    expect(within(details).getByLabelText(/Description/)).toHaveValue(
      "Hello Threads",
    );

    await user.click(
      await within(details).findByRole("button", { name: "Publish now" }),
    );
    const dialog = await screen.findByRole("dialog");
    expect(
      within(dialog).getByText("Hello Threads #cyber"),
    ).toBeInTheDocument();
    await user.click(within(dialog).getByRole("button", { name: "Publish" }));

    expect(
      api.requests.some(
        (request) =>
          request.method === "POST" &&
          request.path === `/publications/${publication.id}/publish`,
      ),
    ).toBe(true);
  });
});
