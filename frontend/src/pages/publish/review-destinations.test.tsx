import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { routes } from "../../routes.tsx";
import { FakeApi } from "../../test-fake-api.ts";
import type { Account, Content, Project, Publication } from "../../types.ts";
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
let inTask: Account;
let free: Account;
let member: Publication;

beforeEach(() => {
  api = new FakeApi();
  api.install();
  project = api.addProject({ name: "L4i4" });
  media = api.addContent({
    project_id: project.id,
    title: "Teaser",
    description: "Media caption",
    hashtags: ["summer"],
  });
  inTask = addTelegram(api, project.id, "news");
  free = addTelegram(api, project.id, "deals");
  member = api.addPublication({ content_id: media.id, account_id: inTask.id });
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

async function openTask(posts = [member.id]) {
  setHealth(api, project.id);
  const view = await openPublish(publishPath(project.id, media.id, posts));
  await screen.findByRole("heading", { level: 2, name: "Review" });
  await view.user.click(
    screen.getByRole("button", { name: "Change destinations" }),
  );
  return view;
}

function addList() {
  return screen.getByRole("list", { name: "Add a destination" });
}

function calls(method: string, pattern: RegExp) {
  return writes(api).filter(
    (request) => request.method === method && pattern.test(request.path),
  );
}

it("adds a destination as a new Draft with an explicit snapshot", async () => {
  const { user, router } = await openTask();
  await user.click(
    within(addList()).getByRole("button", { name: "Add Telegram @deals" }),
  );

  await screen.findByText("Destinations · 2");
  const created = api.publications.find(
    (record) => record.account_id === free.id,
  )!;
  expect(urlPosts(router)).toBe(`${member.id},${created.id}`);
  expect(calls("POST", /\/contents\/\d+\/publications$/)[0].body).toEqual({
    account_ids: [free.id],
    targets: {
      [free.id]: {
        description_override: "Media caption",
        hashtags_override: ["#summer"],
      },
    },
  });
});

it("removes after confirming, and re-adding without a reload reactivates exactly that Post", async () => {
  const { user, router } = await openTask();
  await user.click(
    screen.getByRole("button", { name: "Remove Telegram @news" }),
  );
  const dialog = await screen.findByRole("dialog", {
    name: "Remove Telegram @news?",
  });
  await user.click(within(dialog).getByRole("button", { name: "Remove" }));

  await screen.findByText("Destinations · 0");
  expect(api.publications.find((p) => p.id === member.id)!.status).toBe(
    "cancelled",
  );
  expect(urlPosts(router)).toBe("");

  await user.click(
    within(addList()).getByRole("button", { name: "Add Telegram @news" }),
  );
  await screen.findByText("Destinations · 1");
  expect(calls("POST", /\/reactivate$/).map((request) => request.path)).toEqual(
    [`/publications/${member.id}`.concat("/reactivate")],
  );
  expect(calls("POST", /\/contents\/\d+\/publications$/)).toEqual([]);
  expect(urlPosts(router)).toBe(String(member.id));
  expect(api.publications.find((p) => p.id === member.id)!.status).toBe(
    "unscheduled",
  );
});

it("after a reload, re-adding creates a new Draft and never reactivates a historical one", async () => {
  // Removed in an earlier session: cancelled, and no longer in the URL.
  api.publications.find((p) => p.id === member.id)!.status = "cancelled";
  const other = api.addPublication({
    content_id: media.id,
    account_id: free.id,
  });
  const { user, router } = await openTask([other.id]);

  await user.click(
    within(addList()).getByRole("button", { name: "Add Telegram @news" }),
  );
  await screen.findByText("Destinations · 2");
  expect(calls("POST", /\/reactivate$/)).toEqual([]);
  const created = api.publications.at(-1)!;
  expect(created.id).not.toBe(member.id);
  expect(created.account_id).toBe(inTask.id);
  expect(urlPosts(router)).toBe(`${other.id},${created.id}`);
});

it("a re-add that conflicts shows why and creates nothing", async () => {
  const { user } = await openTask();
  await user.click(
    screen.getByRole("button", { name: "Remove Telegram @news" }),
  );
  await user.click(
    within(await screen.findByRole("dialog")).getByRole("button", {
      name: "Remove",
    }),
  );
  await screen.findByText("Destinations · 0");
  // Meanwhile, another tab created an active Post for that account.
  api.addPublication({
    content_id: media.id,
    account_id: inTask.id,
    scheduled_at: "2099-01-01T10:00:00Z",
  });
  const count = api.publications.length;

  await user.click(
    within(addList()).getByRole("button", { name: "Add Telegram @news" }),
  );
  expect(
    await screen.findByText(
      /Telegram @news: .*already has an active publication/,
    ),
  ).toBeInTheDocument();
  expect(api.publications).toHaveLength(count);
  expect(screen.getByText("Destinations · 0")).toBeInTheDocument();
});

it("a Draft outside the set can be added to this task without any write; other active Posts still block", async () => {
  const outside = api.addPublication({
    content_id: media.id,
    account_id: free.id,
  });
  const busy = addTelegram(api, project.id, "busy");
  const scheduled = api.addPublication({
    content_id: media.id,
    account_id: busy.id,
    scheduled_at: "2099-01-01T10:00:00Z",
    auto_publish_enabled: true,
  });
  const { user, router } = await openTask();

  const deals = within(addList()).getByText("Telegram @deals").closest("li")!;
  expect(within(deals).getByText(/Has a draft/)).toBeInTheDocument();
  const busyRow = within(addList()).getByText("Telegram @busy").closest("li")!;
  expect(
    within(busyRow).getByRole("link", { name: "View post" }),
  ).toHaveAttribute("href", `/p/${project.id}/posts/${scheduled.id}`);
  expect(within(busyRow).queryByRole("button")).toBeNull();

  await user.click(
    within(deals).getByRole("button", {
      name: "Add the draft of Telegram @deals to this task",
    }),
  );
  await screen.findByText("Destinations · 2");
  expect(urlPosts(router)).toBe(`${member.id},${outside.id}`);
  expect(writes(api)).toEqual([]);
});

it("in Compose, Add to this task opens Review with that Draft (no write)", async () => {
  const outside = api.addPublication({
    content_id: media.id,
    account_id: free.id,
  });
  setHealth(api, project.id);
  // ?posts= present but empty: no Resume, Compose shows the Draft.
  const user = userEvent.setup();
  const router = createMemoryRouter(routes, {
    initialEntries: [`${publishPath(project.id, media.id)}?posts=`],
  });
  render(<RouterProvider router={router} />);
  const destinations = await screen.findByRole("group", {
    name: "Destinations",
  });
  await user.click(
    within(destinations).getByRole("button", {
      name: "Add the draft of Telegram @deals to this task",
    }),
  );
  await screen.findByRole("heading", { level: 2, name: "Review" });
  expect(urlPosts(router)).toBe(String(outside.id));
  expect(writes(api)).toEqual([]);
});
