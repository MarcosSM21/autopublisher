import { cleanup, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { FakeApi } from "../../test-fake-api.ts";
import type { Content, Project, Publication } from "../../types.ts";
import {
  addTelegram,
  openPublish,
  publishPath,
  setHealth,
  writes,
} from "./test-publish.ts";

let api: FakeApi;
let project: Project;
let media: Content;
let legacy: Publication;
let snapshotA: Publication;
let snapshotB: Publication;
let other: Publication;

beforeEach(() => {
  api = new FakeApi();
  api.install();
  project = api.addProject({ name: "L4i4" });
  media = api.addContent({
    project_id: project.id,
    description: "Media caption",
    hashtags: ["summer"],
  });
  const draft = (handle: string, values: Partial<Publication> = {}) =>
    api.addPublication({
      content_id: media.id,
      account_id: addTelegram(api, project.id, handle).id,
      ...values,
    });
  // A legacy draft follows the Media; 019 drafts keep an explicit snapshot.
  legacy = draft("legacy");
  snapshotA = draft("a", {
    description_override: "Media caption",
    hashtags_override: ["summer"],
  });
  snapshotB = draft("b", {
    description_override: "Media caption",
    hashtags_override: ["summer"],
  });
  other = draft("c", { description_override: "Other", hashtags_override: [] });
  setHealth(api, project.id);
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

async function open() {
  const view = await openPublish(
    publishPath(project.id, media.id, [
      legacy.id,
      snapshotA.id,
      snapshotB.id,
      other.id,
    ]),
  );
  const section = await screen.findByRole("region", {
    name: "Content by destination",
  });
  return { ...view, section };
}

function patches() {
  return writes(api).filter((request) => request.method === "PATCH");
}

it("shows each Draft's saved content with its provenance, grouping only equal value and provenance", async () => {
  const { section } = await open();
  const groups = within(section)
    .getAllByRole("listitem")
    .filter((item) => item.classList.contains("ap-content-group"));
  expect(groups.map((group) => group.querySelector("p")?.textContent)).toEqual([
    "Telegram @legacy",
    "Telegram @a, Telegram @b",
    "Telegram @c",
  ]);
  // Same text as the Media, but inherited vs explicit: not grouped.
  expect(
    within(groups[0]).getByText("Uses the media's caption"),
  ).toBeInTheDocument();
  expect(within(groups[1]).getByText("Custom text")).toBeInTheDocument();
  expect(within(section).queryByText(/common/i)).toBeNull();
  // Side by side, each Customize says which destination it edits.
  expect(within(groups[1]).getByText("Customize Telegram @a")).toBeVisible();
  expect(within(groups[0]).getByText("Customize")).toBeVisible();
});

it("Edit for these destinations changes only the chosen ones, saying which", async () => {
  const { user, section } = await open();
  await user.click(
    within(section).getByRole("button", {
      name: "Edit for these destinations",
    }),
  );
  const dialog = await screen.findByRole("dialog", {
    name: "Edit for these destinations",
  });
  await user.click(
    within(dialog).getByRole("checkbox", { name: "Telegram @a" }),
  );
  await user.click(
    within(dialog).getByRole("checkbox", { name: "Telegram @c" }),
  );
  expect(
    within(dialog).getByText("Will change: Telegram @a, Telegram @c"),
  ).toBeInTheDocument();
  const caption = within(dialog).getByLabelText("Caption");
  await user.clear(caption);
  await user.type(caption, "Shared now");
  await user.click(within(dialog).getByRole("button", { name: "Save" }));

  await screen.findByText("Telegram @a, Telegram @c");
  expect(patches().map((request) => request.path)).toEqual([
    `/publications/${snapshotA.id}`,
    `/publications/${other.id}`,
  ]);
  // Explicit text (the fake normalizes the hashtags of the logged body).
  expect(patches()[0].body).toEqual({
    description_override: "Shared now",
    hashtags_override: ["summer"],
  });
});

it("Use the media's caption sends null so the Draft follows the Media again", async () => {
  const { user, section } = await open();
  await user.click(
    within(section).getByRole("button", {
      name: "Use the media's caption for Telegram @c",
    }),
  );
  await screen.findByText("Telegram @legacy, Telegram @c");
  expect(patches()).toEqual([
    {
      method: "PATCH",
      path: `/publications/${other.id}`,
      body: { description_override: null, hashtags_override: null },
    },
  ]);
});

it("Customize edits a single destination", async () => {
  const { user, section } = await open();
  await user.click(
    within(section).getByRole("button", { name: "Customize Telegram @legacy" }),
  );
  const dialog = await screen.findByRole("dialog", {
    name: "Customize Telegram @legacy",
  });
  expect(within(dialog).getByLabelText("Caption")).toHaveValue("Media caption");
  await user.type(within(dialog).getByLabelText("Caption"), "!");
  await user.click(within(dialog).getByRole("button", { name: "Save" }));
  await screen.findByText("Media caption!");
  expect(patches().map((request) => request.path)).toEqual([
    `/publications/${legacy.id}`,
  ]);
});
