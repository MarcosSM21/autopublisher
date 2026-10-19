import { cleanup, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { FakeApi } from "../../test-fake-api.ts";
import type { Account, Content, Project } from "../../types.ts";
import {
  addTelegram,
  openPublish,
  publishPath,
  setHealth,
  urlPosts,
  writes,
} from "./test-publish.ts";

let api: FakeApi;
let project: Project;
let media: Content;
let youtube: Account;
let telegram: Account;
let instagram: Account;

beforeEach(() => {
  api = new FakeApi();
  api.install();
  project = api.addProject({ name: "L4i4" });
  media = api.addContent({
    project_id: project.id,
    media_type: "video",
    media_format: "mp4",
    title: "Summer teaser",
    description: "Media caption",
    hashtags: ["summer"],
  });
  youtube = api.addAccount({
    project_id: project.id,
    platform: "youtube",
    handle: "chan",
  });
  telegram = addTelegram(api, project.id, "news");
  instagram = api.addAccount({
    project_id: project.id,
    platform: "instagram",
    handle: "l4i4",
  });
  setHealth(api, project.id);
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function destinations() {
  return screen.getByRole("group", { name: "Destinations" });
}

function checkbox(name: RegExp) {
  return within(destinations()).getByRole("checkbox", { name });
}

function createBodies() {
  return api.requests
    .filter(
      (request) =>
        request.method === "POST" &&
        request.path === `/contents/${media.id}/publications`,
    )
    .map((request) => request.body);
}

async function compose() {
  const view = await openPublish(publishPath(project.id, media.id));
  await screen.findByRole("group", { name: "Destinations" });
  return view;
}

it("writes nothing while composing: selection, preset, content and customization", async () => {
  api.presets.push({
    id: 500,
    project_id: project.id,
    name: "Video",
    account_ids: [youtube.id, telegram.id],
    created_at: "2026-10-05T10:00:00Z",
    updated_at: "2026-10-05T10:00:00Z",
  });
  const { user } = await compose();

  await user.selectOptions(screen.getByLabelText("Preset"), "Video");
  expect(checkbox(/YouTube/)).toBeChecked();
  expect(checkbox(/Telegram/)).toBeChecked();
  await user.click(checkbox(/Instagram/));
  const caption = screen.getByLabelText("Caption");
  await user.clear(caption);
  await user.type(caption, "New words");
  await user.click(
    screen.getByRole("button", { name: "Customize YouTube @chan" }),
  );
  await user.type(screen.getByLabelText("Title for YouTube @chan"), "!");

  expect(writes(api)).toEqual([]);
});

it("opens one customization form at a time, with a title only for YouTube", async () => {
  const { user } = await compose();
  await user.click(checkbox(/YouTube/));
  await user.click(checkbox(/Telegram/));
  expect(
    screen.getByText("Used for all selected destinations unless customized."),
  ).toBeInTheDocument();

  await user.click(
    screen.getByRole("button", { name: "Customize YouTube @chan" }),
  );
  expect(screen.getByLabelText("Title for YouTube @chan")).toHaveValue(
    "Summer teaser",
  );
  await user.click(
    screen.getByRole("button", { name: "Customize Telegram @news" }),
  );
  expect(screen.queryByLabelText("Title for YouTube @chan")).toBeNull();
  expect(screen.getByLabelText("Caption for Telegram @news")).toHaveValue(
    "Media caption",
  );
  expect(screen.queryByLabelText(/^Title for Telegram/)).toBeNull();
});

it("Continue sends the explicit snapshot, then the URL names the created Drafts", async () => {
  const { user, router } = await compose();
  await user.click(checkbox(/Telegram/));
  await user.click(checkbox(/YouTube/));
  await user.click(
    screen.getByRole("button", { name: "Customize Telegram @news" }),
  );
  const custom = screen.getByLabelText("Caption for Telegram @news");
  await user.clear(custom);

  await user.click(screen.getByRole("button", { name: "Continue" }));

  expect(
    await screen.findByRole("heading", { level: 2, name: "Review" }),
  ).toHaveFocus();
  expect(createBodies()).toEqual([
    {
      account_ids: [youtube.id, telegram.id],
      targets: {
        [youtube.id]: {
          description_override: "Media caption",
          hashtags_override: ["#summer"],
          title_override: "Summer teaser",
        },
        // An emptied caption is an explicit "".
        [telegram.id]: {
          description_override: "",
          hashtags_override: ["#summer"],
        },
      },
    },
  ]);
  const created = api.publications.map((record) => record.id);
  expect(urlPosts(router)).toBe(created.join(","));
  // Nothing scheduled, armed or published.
  expect(
    api.publications.every((record) => record.status === "unscheduled"),
  ).toBe(true);
});

it("a rejected destination creates nothing, keeps the input and flags it", async () => {
  api.failRequest("POST", `/contents/${media.id}/publications`, 409, {
    error: {
      code: "duplicate",
      message:
        "Some accounts already have an active publication of this content.",
      fields: [
        {
          field: "account_ids",
          message:
            "Telegram @news already has an active publication of this content.",
          account_id: telegram.id,
        },
      ],
    },
  });
  const { user, router } = await compose();
  await user.click(checkbox(/YouTube/));
  await user.click(checkbox(/Telegram/));
  const caption = screen.getByLabelText("Caption");
  await user.clear(caption);
  await user.type(caption, "Kept");
  await user.click(screen.getByRole("button", { name: "Continue" }));

  const summary = await screen.findByRole("alert");
  expect(summary).toHaveFocus();
  expect(
    within(summary).getByRole("link", {
      name: "Telegram @news already has an active publication of this content.",
    }),
  ).toBeInTheDocument();
  expect(api.publications).toEqual([]);
  expect(urlPosts(router)).toBeNull();
  expect(checkbox(/YouTube/)).toBeChecked();
  expect(checkbox(/Telegram/)).toHaveAttribute("aria-invalid", "true");
  expect(screen.getByLabelText("Caption")).toHaveValue("Kept");
});

it("Continue without destinations shows a focused error summary", async () => {
  const { user } = await compose();
  await user.click(screen.getByRole("button", { name: "Continue" }));
  const summary = await screen.findByRole("alert");
  expect(summary).toHaveFocus();
  await user.click(
    within(summary).getByRole("link", {
      name: "Choose at least one destination.",
    }),
  );
  expect(checkbox(/YouTube/)).toHaveFocus();
  expect(writes(api)).toEqual([]);
});

it("unavailable destinations stay visible with their reason and link", async () => {
  setHealth(api, project.id, { [instagram.id]: { state: "reconnect_needed" } });
  const published = api.addPublication({
    content_id: media.id,
    account_id: youtube.id,
    status: "published",
  });
  const scheduled = api.addPublication({
    content_id: media.id,
    account_id: telegram.id,
    scheduled_at: "2099-01-01T10:00:00Z",
    auto_publish_enabled: true,
  });
  await compose();

  // A published post doesn't block a new one.
  expect(published.status).toBe("published");
  expect(checkbox(/YouTube/)).toBeEnabled();
  expect(checkbox(/Telegram/)).toBeDisabled();
  expect(
    within(destinations()).getByText(/Already scheduled/),
  ).toBeInTheDocument();
  expect(
    within(destinations()).getByRole("link", { name: "View post" }),
  ).toHaveAttribute("href", `/p/${project.id}/posts/${scheduled.id}`);
  expect(checkbox(/Instagram/)).toBeDisabled();
  expect(
    within(destinations()).getByText(/Reconnect account/),
  ).toBeInTheDocument();
  expect(
    within(destinations()).getByRole("link", { name: "Open account" }),
  ).toHaveAttribute("href", `/p/${project.id}/accounts/${instagram.id}`);
});
