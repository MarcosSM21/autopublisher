import { act, cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { routes } from "../../routes.tsx";
import { FakeApi } from "../../test-fake-api.ts";
import { renderRoute } from "../../test-utils.tsx";
import type { Account, Content, Project } from "../../types.ts";
import { setHealth } from "../publish/test-publish.ts";

let api: FakeApi;
let project: Project;
let media: Content;
let handle = 0;

beforeEach(() => {
  api = new FakeApi();
  api.install();
  project = api.addProject({ name: "L4i4" });
  media = api.addContent({ project_id: project.id, title: "Teaser" });
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function account(): Account {
  return api.addAccount({
    project_id: project.id,
    platform: "youtube",
    handle: `chan${(handle += 1)}`,
  });
}

const soon = (days: number) =>
  new Date(Date.now() + days * 86_400_000).toISOString();

async function openPosts(path = `/p/${project.id}/posts`) {
  // Every account Ready unless a test says otherwise (no Blocked readiness).
  setHealth(api, project.id);
  const user = userEvent.setup();
  const view = renderRoute(path);
  await screen.findByRole("heading", { level: 1, name: "Posts" });
  return { user, ...view };
}

function section(name: RegExp) {
  return screen.getByRole("region", { name });
}

it("groups the day by meaning, one section per Post, with hints and one paused banner", async () => {
  api.automation.paused = true;
  const failed = api.addPublication({
    content_id: media.id,
    account_id: account().id,
    status: "failed",
  });
  const incomplete = api.addPublication({
    content_id: media.id,
    account_id: account().id,
    scheduled_at: soon(2),
    auto_publish_enabled: true,
  });
  api.addPublication({
    content_id: media.id,
    account_id: account().id,
    scheduled_at: soon(3),
    auto_publish_enabled: true,
  });
  api.addPublication({
    content_id: media.id,
    account_id: account().id,
    scheduled_at: soon(20),
  });
  api.addPublication({ content_id: media.id, account_id: account().id });
  api.addPublication({
    content_id: media.id,
    account_id: account().id,
    status: "published",
    published_at: soon(-1),
  });
  api.projectOverviews.set(project.id, {
    ...api.emptyOverview([project]),
    automation: { paused: true, running: true, paused_automatic_posts: 2 },
    attention: [
      {
        kind: "incomplete",
        priority: 6,
        project: { id: project.id, name: project.name },
        account: { id: 1, platform: "youtube", label: "x" },
        post: {
          id: incomplete.id,
          display_state: "scheduled_paused",
          scheduled_at: soon(2),
          media_title: null,
          excerpt: null,
        },
        title: "Needs details before publishing",
        detail: "Declare whether the video is made for kids.",
        at: soon(2),
        action: {
          label: "Complete",
          target: { type: "post", id: incomplete.id },
        },
        affected_posts: 0,
      },
    ],
  });
  await openPosts();

  const needsYou = await screen.findByRole("region", { name: "Needs you · 2" });
  const rows = within(needsYou).getAllByRole("link");
  expect(rows[0]).toHaveAttribute(
    "href",
    `/p/${project.id}/posts/${failed.id}`,
  );
  expect(rows[0]).toHaveTextContent("Retry or reschedule");
  expect(rows[1]).toHaveTextContent(
    "Add details · Declare whether the video is made for kids.",
  );
  const upcoming = section(/^Upcoming · 2/);
  expect(within(upcoming).getAllByRole("link")).toHaveLength(2);
  expect(section(/^Drafts · 1/)).toBeInTheDocument();
  // Published lives in History only.
  expect(screen.queryByRole("region", { name: /History/ })).toBeNull();
  expect(
    screen.getAllByRole("region", { name: "Automatic publishing is paused" }),
  ).toHaveLength(1);
  // The pause is said once (rows only carry their state badge).
  expect(screen.queryAllByText(/won't publish until you resume/)).toHaveLength(
    1,
  );
});

it("hides Needs you when nothing needs the user", async () => {
  api.addPublication({ content_id: media.id, account_id: account().id });
  await openPosts();
  await screen.findByRole("region", { name: "Drafts · 1" });
  expect(screen.queryByRole("region", { name: /Needs you/ })).toBeNull();
  expect(
    screen.queryByRole("region", { name: /Automatic publishing is paused/ }),
  ).toBeNull();
});

it("shows History by month with Show more", async () => {
  for (let index = 0; index < 32; index += 1) {
    api.addPublication({
      content_id: media.id,
      account_id: account().id,
      status: "published",
      published_at: index < 2 ? "2026-09-10T10:00:00Z" : "2026-10-10T10:00:00Z",
    });
  }
  const { user } = await openPosts(`/p/${project.id}/posts?view=history`);
  await screen.findByRole("heading", { level: 2, name: "History" });
  expect(screen.getAllByRole("link", { name: /Teaser/ })).toHaveLength(30);
  expect(screen.getByText("Showing 30 of 32")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Show more" }));
  expect(screen.getAllByRole("link", { name: /Teaser/ })).toHaveLength(32);
  expect(
    screen.getByRole("heading", { level: 3, name: /September 2026/ }),
  ).toBeInTheDocument();
});

it("search and destination filter every section and live in the URL", async () => {
  const other = api.addContent({ project_id: project.id, title: "Winter" });
  const telegram = api.addAccount({
    project_id: project.id,
    platform: "telegram",
    handle: "news",
  });
  api.addPublication({ content_id: media.id, account_id: account().id });
  api.addPublication({ content_id: other.id, account_id: telegram.id });
  const { user, router } = await openPosts();
  await screen.findByRole("region", { name: "Drafts · 2" });

  await user.type(screen.getByLabelText("Search posts"), "winter");
  expect(
    await screen.findByRole("region", { name: "Drafts · 1" }),
  ).toBeInTheDocument();
  expect(new URLSearchParams(router.state.location.search).get("q")).toBe(
    "winter",
  );
  await user.clear(screen.getByLabelText("Search posts"));
  await user.selectOptions(
    screen.getByLabelText("Destination"),
    "Telegram @news",
  );
  expect(
    await screen.findByRole("region", { name: "Drafts · 1" }),
  ).toHaveTextContent("Winter");
});

it("opening a Post keeps the list mounted with its search", async () => {
  const draft = api.addPublication({
    content_id: media.id,
    account_id: account().id,
  });
  const { user, router } = await openPosts(`/p/${project.id}/posts?q=teaser`);
  const list = await screen.findByRole("region", { name: "Drafts · 1" });
  await user.click(within(list).getByRole("link", { name: /Teaser/ }));
  expect(router.state.location.pathname).toBe(
    `/p/${project.id}/posts/${draft.id}`,
  );
  expect(router.state.location.search).toBe("?q=teaser");
  expect(
    await screen.findByRole("region", { name: "Post details" }),
  ).toBeInTheDocument();
  // On a phone the detail is a full page: the list is hidden, not unmounted.
  expect(list).toBeInTheDocument();
  expect(list).not.toBeVisible();
  expect(screen.getByLabelText("Search posts")).toHaveValue("teaser");
  expect(
    within(list).getByRole("link", { name: /Teaser/, hidden: true }),
  ).toHaveAttribute("aria-current", "true");
});

it("arriving from Finish later focuses the Drafts", async () => {
  api.addPublication({ content_id: media.id, account_id: account().id });
  const router = createMemoryRouter(routes, {
    initialEntries: [
      { pathname: `/p/${project.id}/posts`, state: { focus: "drafts" } },
    ],
  });
  render(<RouterProvider router={router} />);
  expect(
    await screen.findByRole("heading", { name: "Drafts · 1" }),
  ).toHaveFocus();
});

it("New post offers Publish media… and Text post", async () => {
  api.addPublication({ content_id: media.id, account_id: account().id });
  const { user, router } = await openPosts();
  await user.click(screen.getByRole("button", { name: "New post" }));
  expect(screen.getByRole("link", { name: /Publish media…/ })).toHaveAttribute(
    "href",
    `/p/${project.id}/library`,
  );
  await user.click(screen.getByRole("link", { name: /Text post/ }));
  expect(router.state.location.pathname).toBe(`/p/${project.id}/posts/new`);
  expect(
    await screen.findByRole("heading", { level: 1, name: /Text post/ }),
  ).toBeInTheDocument();
  await act(async () => {});
});

it("the New post menu closes on an outside click, on Escape and on Tab away", async () => {
  api.addPublication({ content_id: media.id, account_id: account().id });
  const { user } = await openPosts();
  const toggle = screen.getByRole("button", { name: "New post" });
  const textPost = () => screen.queryByRole("link", { name: /Text post/ });

  await user.click(toggle);
  expect(textPost()).toBeVisible();
  await user.click(screen.getByRole("heading", { level: 1, name: "Posts" }));
  expect(toggle).toHaveAttribute("aria-expanded", "false");
  expect(textPost()).toBeNull();

  await user.click(toggle);
  await user.keyboard("{Escape}");
  expect(toggle).toHaveAttribute("aria-expanded", "false");
  expect(toggle).toHaveFocus();

  await user.click(toggle);
  await user.tab();
  await user.tab();
  expect(textPost()).toHaveFocus();
  await user.tab();
  expect(toggle).toHaveAttribute("aria-expanded", "false");
});

it("closing a Post detail gives the focus back to its row", async () => {
  api.addPublication({ content_id: media.id, account_id: account().id });
  const { user } = await openPosts();
  const list = await screen.findByRole("region", { name: "Drafts · 1" });
  await user.click(within(list).getByRole("link", { name: /Teaser/ }));
  await user.click(await screen.findByRole("button", { name: "Back" }));
  expect(within(list).getByRole("link", { name: /Teaser/ })).toHaveFocus();
});
