import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { FakeApi } from "../test-fake-api.ts";
import type { Account, Content, Project } from "../types.ts";
import ProjectDetail from "./ProjectDetail.tsx";

const FUTURE = "2100-01-01T10:00:00.000Z";
const LATER = "2100-02-01T18:30:00.000Z";
const PAST = "2000-01-01T10:00:00.000Z";

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
  content = api.addContent({
    project_id: project.id,
    title: "Summer teaser",
    description: "Global description",
    hashtags: ["l4i4", "summer"],
  });
  instagram = api.addAccount({
    project_id: project.id,
    platform: "instagram",
    handle: "l4i4",
  });
  tiktok = api.addAccount({
    project_id: project.id,
    platform: "tiktok",
    handle: "l4i4",
  });
  x = api.addAccount({ project_id: project.id, platform: "x", handle: "l4i4" });
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

async function openQueue(selected: Project = project) {
  const user = userEvent.setup();
  render(<ProjectDetail project={selected} onProjectChanged={vi.fn()} />);
  await user.click(screen.getByRole("button", { name: "Queue" }));
  return user;
}

function section(label: string) {
  return screen.getByRole("list", { name: `${label} publications` });
}

async function openDetail(name: RegExp) {
  const user = await openQueue();
  await user.click(await screen.findByRole("button", { name }));
  return user;
}

function patches() {
  return api.requests.filter((request) => request.method === "PATCH");
}

describe("queue", () => {
  it("shows an empty state", async () => {
    await openQueue();
    expect(
      await screen.findByText(
        "No publications yet. Open a content and choose Prepare publications.",
      ),
    ).toBeInTheDocument();
  });

  it("groups publications by status in queue order", async () => {
    api.addPublication({
      content_id: content.id,
      account_id: x.id,
      status: "cancelled",
    });
    api.addPublication({ content_id: content.id, account_id: tiktok.id });
    api.addPublication({
      content_id: content.id,
      account_id: instagram.id,
      scheduled_at: FUTURE,
    });
    await openQueue();

    await screen.findByRole("region", { name: "Publication queue" });
    expect(
      screen.getAllByRole("heading", { level: 4 }).map((h) => h.textContent),
    ).toEqual(["Scheduled (1)", "Unscheduled (1)", "Cancelled (1)"]);
    const scheduled = within(section("Scheduled")).getByRole("button");
    expect(scheduled).toHaveTextContent("Summer teaser");
    expect(scheduled).toHaveTextContent("Instagram @l4i4");
    expect(scheduled).toHaveTextContent("Scheduled");
    expect(scheduled).toHaveTextContent(new Date(FUTURE).toLocaleString());
    expect(scheduled.querySelector("img")).not.toBeNull();
    expect(section("Unscheduled")).toHaveTextContent("TikTok @l4i4");
    expect(section("Cancelled")).toHaveTextContent("X @l4i4");
  });

  it("marks overdue publications, inactive accounts and missing files", async () => {
    api.addPublication({
      content_id: content.id,
      account_id: instagram.id,
      scheduled_at: PAST,
    });
    tiktok.is_active = false;
    api.addPublication({ content_id: content.id, account_id: tiktok.id });
    content.file_available = false;
    await openQueue();

    await screen.findByRole("region", { name: "Publication queue" });
    expect(section("Scheduled")).toHaveTextContent("Overdue");
    expect(section("Unscheduled")).toHaveTextContent("Account inactive");
    expect(screen.getAllByText("File not available")).toHaveLength(2);
  });

  it("still lists the publications of an inactive project", async () => {
    project.is_active = false;
    api.addPublication({ content_id: content.id, account_id: x.id });
    await openQueue();

    expect(await screen.findByText(/This project is inactive/)).toBeVisible();
    expect(section("Unscheduled")).toHaveTextContent("X @l4i4");
  });

  it("renders a large queue", async () => {
    for (let index = 0; index < 200; index += 1) {
      const item = api.addContent({ project_id: project.id });
      api.addPublication({ content_id: item.id, account_id: x.id });
    }
    await openQueue();

    await screen.findByRole("region", { name: "Publication queue" });
    expect(
      within(section("Unscheduled")).getAllByRole("listitem"),
    ).toHaveLength(200);
  });
});

describe("scheduling", () => {
  it("sets a date and moves the publication to Scheduled", async () => {
    api.addPublication({ content_id: content.id, account_id: instagram.id });
    const user = await openDetail(/Instagram/);

    await user.type(screen.getByLabelText("Publish at"), "2100-03-15T18:45");
    await user.click(screen.getByRole("button", { name: "Save date" }));

    expect(patches()[0].body).toEqual({
      scheduled_at: new Date(2100, 2, 15, 18, 45).toISOString(),
    });
    expect(
      await within(section("Scheduled")).findByText("Instagram @l4i4"),
    ).toBeInTheDocument();
  });

  it("removes the date", async () => {
    api.addPublication({
      content_id: content.id,
      account_id: tiktok.id,
      scheduled_at: LATER,
    });
    const user = await openDetail(/TikTok/);

    await user.click(screen.getByRole("button", { name: "Remove date" }));

    expect(patches()[0].body).toEqual({ scheduled_at: null });
    expect(
      await within(section("Unscheduled")).findByText("TikTok @l4i4"),
    ).toBeInTheDocument();
  });

  it("shows a date error without losing the value", async () => {
    api.addPublication({ content_id: content.id, account_id: instagram.id });
    const user = await openDetail(/Instagram/);
    api.failNext(422, {
      error: {
        code: "validation_error",
        message: "The request contains invalid data.",
        fields: [
          {
            field: "scheduled_at",
            message: "Choose a date and time in the future.",
          },
        ],
      },
    });

    await user.type(screen.getByLabelText("Publish at"), "2000-01-01T10:00");
    await user.click(screen.getByRole("button", { name: "Save date" }));

    expect(
      await screen.findByText("Choose a date and time in the future."),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Publish at")).toHaveValue("2000-01-01T10:00");
  });

  it("explains why a publication cannot be scheduled", async () => {
    instagram.is_active = false;
    api.addPublication({
      content_id: content.id,
      account_id: instagram.id,
      scheduled_at: FUTURE,
    });
    await openDetail(/Instagram/);

    expect(screen.getByRole("button", { name: "Save date" })).toBeDisabled();
    expect(
      screen.getByText("Reactivate the account to schedule this publication."),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Remove date" })).toBeEnabled();
  });
});

describe("metadata overrides", () => {
  it("uses the content's metadata by default", async () => {
    api.addPublication({ content_id: content.id, account_id: instagram.id });
    await openDetail(/Instagram/);

    const form = screen.getByRole("form", { name: "Metadata" });
    expect(within(form).getAllByText("Using content value")).toHaveLength(3);
    expect(within(form).getByText("Global description")).toBeInTheDocument();
    expect(within(form).getByText("#l4i4 #summer")).toBeInTheDocument();
  });

  it("customizes one field", async () => {
    api.addPublication({ content_id: content.id, account_id: instagram.id });
    const user = await openDetail(/Instagram/);

    await user.click(
      screen.getByRole("button", { name: "Customize description" }),
    );
    const field = screen.getByRole("textbox", { name: /Description/ });
    expect(field).toHaveValue("Global description");
    await user.clear(field);
    await user.type(field, "Link in bio");
    await user.click(screen.getByRole("button", { name: "Save metadata" }));

    expect(patches()[0].body).toEqual({ description_override: "Link in bio" });
    const form = await screen.findByRole("form", { name: "Metadata" });
    expect(await within(form).findByText("Customized")).toBeInTheDocument();
    expect(content.description).toBe("Global description");
  });

  it("goes back to the content's value", async () => {
    api.addPublication({
      content_id: content.id,
      account_id: instagram.id,
      description_override: "Custom",
    });
    const user = await openDetail(/Instagram/);

    await user.click(
      screen.getByRole("button", {
        name: "Use content value for description",
      }),
    );
    await user.click(screen.getByRole("button", { name: "Save metadata" }));

    expect(patches()[0].body).toEqual({ description_override: null });
  });

  it("saves an explicitly empty hashtags override", async () => {
    api.addPublication({ content_id: content.id, account_id: x.id });
    const user = await openDetail(/X @l4i4/);

    await user.click(
      screen.getByRole("button", { name: "Customize hashtags" }),
    );
    await user.clear(screen.getByRole("textbox", { name: /Hashtags/ }));
    await user.click(screen.getByRole("button", { name: "Save metadata" }));

    expect(patches()[0].body).toEqual({ hashtags_override: [] });
  });

  it("keeps the typed text when the server rejects it", async () => {
    api.addPublication({ content_id: content.id, account_id: instagram.id });
    const user = await openDetail(/Instagram/);
    api.failNext(422, {
      error: {
        code: "validation_error",
        message: "The request contains invalid data.",
        fields: [
          {
            field: "title_override",
            message: "Must be at most 200 characters.",
          },
        ],
      },
    });

    await user.click(screen.getByRole("button", { name: "Customize title" }));
    const field = screen.getByRole("textbox", { name: /Title/ });
    await user.clear(field);
    await user.type(field, "Too long");
    await user.click(screen.getByRole("button", { name: "Save metadata" }));

    expect(
      await screen.findByText("Must be at most 200 characters."),
    ).toBeInTheDocument();
    expect(field).toHaveValue("Too long");
  });
});

describe("cancel and reactivate", () => {
  it("cancels a publication and keeps it in the queue", async () => {
    api.addPublication({
      content_id: content.id,
      account_id: instagram.id,
      scheduled_at: FUTURE,
    });
    const user = await openDetail(/Instagram/);

    await user.click(
      screen.getByRole("button", { name: "Cancel publication" }),
    );

    expect(
      await within(section("Cancelled")).findByText("Instagram @l4i4"),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reactivate" })).toBeEnabled();
    expect(
      screen.queryByRole("button", { name: "Save date" }),
    ).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /delete/i })).toBeNull();
  });

  it("reactivates and warns when the date had passed", async () => {
    api.addPublication({
      content_id: content.id,
      account_id: tiktok.id,
      status: "cancelled",
      scheduled_at: PAST,
    });
    const user = await openDetail(/TikTok/);

    await user.click(screen.getByRole("button", { name: "Reactivate" }));

    expect(
      await screen.findByText(
        "The scheduled date had passed and was removed. Choose a new date.",
      ),
    ).toBeInTheDocument();
    expect(section("Unscheduled")).toHaveTextContent("TikTok @l4i4");
  });

  it("shows a conflict when reactivating", async () => {
    api.addPublication({
      content_id: content.id,
      account_id: x.id,
      status: "cancelled",
    });
    api.addPublication({ content_id: content.id, account_id: x.id });
    const user = await openQueue();
    await user.click(
      await within(
        await screen.findByRole("list", { name: "Cancelled publications" }),
      ).findByRole("button"),
    );

    await user.click(screen.getByRole("button", { name: "Reactivate" }));

    expect(
      await screen.findByText(
        "X @l4i4 already has an active publication of this content.",
      ),
    ).toBeInTheDocument();
  });

  it("explains why a publication cannot be reactivated", async () => {
    content.file_available = false;
    api.addPublication({
      content_id: content.id,
      account_id: x.id,
      status: "cancelled",
    });
    await openDetail(/X @l4i4/);

    expect(screen.getByRole("button", { name: "Reactivate" })).toBeDisabled();
    expect(
      screen.getAllByText("The media file of this content is not available."),
    ).not.toHaveLength(0);
  });
});
