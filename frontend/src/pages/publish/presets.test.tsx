import { cleanup, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { FakeApi } from "../../test-fake-api.ts";
import type { Account, Content, Project } from "../../types.ts";
import {
  addTelegram,
  openPublish,
  publishPath,
  setHealth,
} from "./test-publish.ts";

let api: FakeApi;
let project: Project;
let media: Content;
let youtube: Account;
let news: Account;
let deals: Account;

beforeEach(() => {
  api = new FakeApi();
  api.install();
  project = api.addProject({ name: "L4i4" });
  media = api.addContent({ project_id: project.id });
  news = addTelegram(api, project.id, "news");
  deals = addTelegram(api, project.id, "deals");
  youtube = api.addAccount({
    project_id: project.id,
    platform: "youtube",
    handle: "chan",
  });
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function checkbox(name: RegExp) {
  return within(screen.getByRole("group", { name: "Destinations" })).getByRole(
    "checkbox",
    { name },
  );
}

it("applying a preset replaces the selection and lists what it skipped", async () => {
  setHealth(api, project.id);
  api.presets.push({
    id: 500,
    project_id: project.id,
    name: "Everything",
    account_ids: [youtube.id, news.id],
    created_at: "2026-10-05T10:00:00Z",
    updated_at: "2026-10-05T10:00:00Z",
  });
  const { user } = await openPublish(publishPath(project.id, media.id));
  await screen.findByRole("group", { name: "Destinations" });
  await user.click(checkbox(/deals/));

  await user.selectOptions(screen.getByLabelText("Preset"), "Everything");

  expect(checkbox(/deals/)).not.toBeChecked();
  expect(checkbox(/news/)).toBeChecked();
  const notice = screen.getByRole("status");
  expect(notice).toHaveTextContent(
    "Applied “Everything”. 1 destination skipped:",
  );
  // The Media is an image: YouTube only takes videos.
  expect(notice).toHaveTextContent("YouTube @chan · Video only");
  expect(api.presets[0].account_ids).toEqual([youtube.id, news.id]);
});

it("saves the selection as a preset, rejects a duplicate name and deletes after confirming", async () => {
  setHealth(api, project.id);
  const { user } = await openPublish(publishPath(project.id, media.id));
  await screen.findByRole("group", { name: "Destinations" });
  await user.click(checkbox(/news/));
  await user.click(checkbox(/deals/));

  await user.click(screen.getByRole("button", { name: "Save as preset" }));
  const dialog = await screen.findByRole("dialog", { name: "Presets" });
  await user.type(within(dialog).getByLabelText("Preset name"), "Channels");
  await user.click(
    within(dialog).getByRole("button", { name: "Save as preset" }),
  );
  expect(
    await within(dialog).findByRole("list", { name: "Presets" }),
  ).toHaveTextContent("Channels 2 destinations");
  expect(api.presets[0].account_ids).toEqual([news.id, deals.id]);

  await user.type(within(dialog).getByLabelText("Preset name"), "Channels");
  await user.click(
    within(dialog).getByRole("button", { name: "Save as preset" }),
  );
  expect(
    await within(dialog).findByText("A preset with this name already exists."),
  ).toBeInTheDocument();
  expect(api.presets).toHaveLength(1);

  await user.click(
    within(dialog).getByRole("button", { name: "Delete Channels" }),
  );
  expect(api.presets).toHaveLength(1);
  await user.click(within(dialog).getByRole("button", { name: "Delete" }));
  expect(
    await within(dialog).findByText(/Saves the 2 destinations/),
  ).toBeInTheDocument();
  expect(within(dialog).queryByRole("list", { name: "Presets" })).toBeNull();
  expect(api.presets).toEqual([]);
  // Presets never touch a Post.
  expect(api.publications).toEqual([]);
});
