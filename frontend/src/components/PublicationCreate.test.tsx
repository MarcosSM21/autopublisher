import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { FakeApi } from "../test-fake-api.ts";
import type { Account, Content, Project } from "../types.ts";
import ProjectDetail from "./ProjectDetail.tsx";

let api: FakeApi;
let project: Project;
let content: Content;
let instagram: Account;
let tiktok: Account;
let x: Account;

beforeEach(() => {
  api = new FakeApi();
  api.install();
  project = api.addProject({ name: "L4i4" });
  content = api.addContent({ project_id: project.id, title: "Summer teaser" });
  instagram = api.addAccount({
    project_id: project.id,
    platform: "instagram",
    handle: "l4i4",
    display_name: "L4i4 IG",
  });
  tiktok = api.addAccount({
    project_id: project.id,
    platform: "tiktok",
    handle: "l4i4",
  });
  x = api.addAccount({ project_id: project.id, platform: "x", handle: "l4i4" });
  api.addAccount({
    project_id: project.id,
    platform: "youtube",
    handle: "old",
    is_active: false,
  });
  const other = api.addProject({ name: "Cybersecurity" });
  api.addAccount({
    project_id: other.id,
    platform: "threads",
    handle: "cyber",
  });
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

/** Opens the project's content, selects the content and prepares publications. */
async function openPrepare(selected: Project = project) {
  const user = userEvent.setup();
  render(<ProjectDetail project={selected} onProjectChanged={vi.fn()} />);
  await user.click(screen.getByRole("button", { name: "Content" }));
  await user.click(
    await screen.findByRole("button", { name: /Summer teaser/ }),
  );
  await user.click(
    screen.getByRole("button", { name: "Prepare publications" }),
  );
  return user;
}

function accountsGroup() {
  return screen.findByRole("group", { name: "Target accounts" });
}

function createRequests() {
  return api.requests.filter(
    (request) =>
      request.method === "POST" && request.path.endsWith("/publications"),
  );
}

describe("preparing publications", () => {
  it("lists only the project's active accounts", async () => {
    await openPrepare();

    const group = await accountsGroup();
    const boxes = within(group).getAllByRole("checkbox");
    expect(boxes).toHaveLength(3);
    expect(
      within(group).getByRole("checkbox", {
        name: /Instagram @l4i4 · L4i4 IG/,
      }),
    ).toBeInTheDocument();
    expect(within(group).queryByText(/@old/)).not.toBeInTheDocument();
    expect(within(group).queryByText(/@cyber/)).not.toBeInTheDocument();
  });

  it("creates one publication per selected account", async () => {
    const user = await openPrepare();
    const group = await accountsGroup();
    const create = screen.getByRole("button", { name: "Create publications" });
    expect(create).toBeDisabled();

    for (const name of [/Instagram/, /TikTok/, /^X /]) {
      await user.click(within(group).getByRole("checkbox", { name }));
    }
    await user.click(create);

    expect(createRequests()).toHaveLength(1);
    expect(createRequests()[0]).toMatchObject({
      path: `/contents/${content.id}/publications`,
      body: { account_ids: [instagram.id, tiktok.id, x.id] },
    });
    expect(createRequests()[0].body).not.toHaveProperty("scheduled_at");
    expect(
      await screen.findByText(
        "Created 3 publications for Instagram @l4i4, TikTok @l4i4, X @l4i4.",
      ),
    ).toBeInTheDocument();
  });

  it("sends the chosen local date as an ISO instant", async () => {
    const user = await openPrepare();
    const group = await accountsGroup();
    await user.click(within(group).getByRole("checkbox", { name: /TikTok/ }));
    await user.type(
      screen.getByLabelText("Publish at (optional)"),
      "2100-03-15T18:45",
    );
    await user.click(
      screen.getByRole("button", { name: "Create publications" }),
    );

    expect(createRequests()[0].body).toEqual({
      account_ids: [tiktok.id],
      scheduled_at: new Date(2100, 2, 15, 18, 45).toISOString(),
    });
  });

  it("opens the queue after creating", async () => {
    const user = await openPrepare();
    const group = await accountsGroup();
    await user.click(
      within(group).getByRole("checkbox", { name: /Instagram/ }),
    );
    await user.click(within(group).getByRole("checkbox", { name: /TikTok/ }));
    await user.click(
      screen.getByRole("button", { name: "Create publications" }),
    );
    await user.click(await screen.findByRole("button", { name: "Open queue" }));

    const queue = await screen.findByRole("region", {
      name: "Publication queue",
    });
    expect(within(queue).getAllByRole("listitem")).toHaveLength(2);
    expect(within(queue).getByText(/Instagram/)).toBeInTheDocument();
  });

  it("explains why publications cannot be prepared", async () => {
    project.is_active = false;
    await openPrepare();
    expect(
      await screen.findByText(
        "Reactivate the project to prepare publications.",
      ),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("group", { name: "Target accounts" }),
    ).not.toBeInTheDocument();
  });

  it("asks for an active account when there is none", async () => {
    for (const account of api.accounts) {
      account.is_active = false;
    }
    await openPrepare();
    expect(
      await screen.findByText("Add an active account to this project first."),
    ).toBeInTheDocument();
  });

  it("refuses when the media file is not available", async () => {
    content.file_available = false;
    await openPrepare();
    expect(
      await screen.findAllByText(
        "The media file of this content is not available.",
      ),
    ).not.toHaveLength(0);
    expect(
      screen.queryByRole("group", { name: "Target accounts" }),
    ).not.toBeInTheDocument();
  });

  it("shows server errors per account and keeps the selection", async () => {
    const user = await openPrepare();
    const group = await accountsGroup();
    await user.click(
      within(group).getByRole("checkbox", { name: /Instagram/ }),
    );
    api.failNext(409, {
      error: {
        code: "account_inactive",
        message: "Some accounts are inactive.",
        fields: [
          { field: "account_ids", message: "Instagram @l4i4 is inactive." },
        ],
      },
    });
    await user.click(
      screen.getByRole("button", { name: "Create publications" }),
    );

    expect(
      await screen.findByText("Some accounts are inactive."),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Instagram @l4i4 is inactive."),
    ).toBeInTheDocument();
    expect(
      within(group).getByRole("checkbox", { name: /Instagram/ }),
    ).toBeChecked();
  });
});

describe("duplicate prevention", () => {
  it("disables accounts that already have an active publication", async () => {
    api.addPublication({ content_id: content.id, account_id: instagram.id });
    api.addPublication({
      content_id: content.id,
      account_id: tiktok.id,
      status: "cancelled",
    });
    await openPrepare();

    const group = await accountsGroup();
    const instagramBox = within(group).getByRole("checkbox", {
      name: /Instagram/,
    });
    expect(instagramBox).toBeDisabled();
    expect(
      within(group).getByText("Already has an active publication"),
    ).toBeInTheDocument();
    expect(
      within(group).getByRole("checkbox", { name: /TikTok/ }),
    ).toBeEnabled();
  });

  it("shows the duplicate message returned by the server", async () => {
    const user = await openPrepare();
    const group = await accountsGroup();
    await user.click(within(group).getByRole("checkbox", { name: /^X / }));
    api.failNext(409, {
      error: {
        code: "duplicate",
        message:
          "Some accounts already have an active publication of this content.",
        fields: [
          {
            field: "account_ids",
            message:
              "X @l4i4 already has an active publication of this content.",
          },
        ],
      },
    });
    await user.click(
      screen.getByRole("button", { name: "Create publications" }),
    );

    expect(
      await screen.findByText(
        "X @l4i4 already has an active publication of this content.",
      ),
    ).toBeInTheDocument();
  });
});
