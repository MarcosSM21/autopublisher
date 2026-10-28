import { act, cleanup, render, screen, within } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { routes } from "../../routes.tsx";
import { FakeApi } from "../../test-fake-api.ts";
import { renderRoute } from "../../test-utils.tsx";
import type { Content, Project } from "../../types.ts";
import {
  addTelegram,
  openPublish,
  publishPath,
  setHealth,
  urlPosts,
} from "./test-publish.ts";

let api: FakeApi;
let project: Project;
let media: Content;

beforeEach(() => {
  api = new FakeApi();
  api.install();
  project = api.addProject({ name: "L4i4" });
  media = api.addContent({ project_id: project.id, title: "Summer teaser" });
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function getRequests(path: string) {
  return api.requests.filter(
    (request) => request.method === "GET" && request.path === path,
  );
}

it("without ?posts, a Media with drafts resumes in Review and the URL names them", async () => {
  const a = addTelegram(api, project.id, "news");
  const b = addTelegram(api, project.id, "deals");
  setHealth(api, project.id);
  const first = api.addPublication({ content_id: media.id, account_id: b.id });
  const second = api.addPublication({ content_id: media.id, account_id: a.id });

  const { router } = await openPublish(publishPath(project.id, media.id));

  expect(
    await screen.findByRole("heading", { level: 2, name: "Review" }),
  ).toBeInTheDocument();
  expect(urlPosts(router)).toBe(`${first.id},${second.id}`);
  expect(
    screen.getByText("Your drafts are saved. You can finish them later."),
  ).toBeInTheDocument();
  expect(screen.getAllByRole("region", { name: /^Telegram/ })).toHaveLength(2);
  expect(screen.queryByText(/Created \d/)).not.toBeInTheDocument();
});

it("drops ids of another project or Media (and unknown ones) with a notice", async () => {
  const account = addTelegram(api, project.id, "news");
  setHealth(api, project.id);
  const own = api.addPublication({
    content_id: media.id,
    account_id: account.id,
  });
  const otherMedia = api.addContent({ project_id: project.id });
  const elsewhere = api.addPublication({
    content_id: otherMedia.id,
    account_id: account.id,
  });
  const otherProject = api.addProject({ name: "Other" });
  const foreignMedia = api.addContent({ project_id: otherProject.id });
  const foreignAccount = addTelegram(api, otherProject.id, "far");
  const foreign = api.addPublication({
    content_id: foreignMedia.id,
    account_id: foreignAccount.id,
  });

  const { router } = await openPublish(
    publishPath(project.id, media.id, [foreign.id, own.id, elsewhere.id, 9999]),
  );

  expect(
    await screen.findByText("3 posts couldn't be included."),
  ).toBeInTheDocument();
  expect(urlPosts(router)).toBe(String(own.id));
  expect(screen.getAllByRole("region", { name: /^Telegram/ })).toHaveLength(1);
});

it("a Media of another project is not found", async () => {
  const other = api.addProject({ name: "Other" });
  const foreign = api.addContent({ project_id: other.id });
  const view = renderRoute(publishPath(project.id, foreign.id));
  expect(
    await screen.findByRole("link", { name: "Back to Library" }),
  ).toHaveAttribute("href", `/p/${project.id}/library`);
  expect(view.router.state.location.pathname).toBe(
    publishPath(project.id, foreign.id),
  );
});

it("on phones the task hides the bottom navigation and keeps Back to media", async () => {
  vi.stubGlobal(
    "matchMedia",
    (query: string) =>
      ({
        matches: 375 >= Number(/min-width:\s*(\d+)px/.exec(query)?.[1] ?? 0),
        media: query,
        addEventListener: () => {},
        removeEventListener: () => {},
      }) as unknown as MediaQueryList,
  );
  setHealth(api, project.id);
  await openPublish(publishPath(project.id, media.id));
  expect(
    screen.queryByRole("navigation", { name: "Main" }),
  ).not.toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Back to media" })).toHaveAttribute(
    "href",
    `/p/${project.id}/library/${media.id}`,
  );
  // Compose: its actions in the sticky bar.
  expect(
    await screen.findByRole("group", { name: "Publish actions" }),
  ).toHaveClass("ap-page-actions--sticky");
});

it("a reload rebuilds the set from ?posts=, polling only the post being published", async () => {
  const a = addTelegram(api, project.id, "news");
  const b = addTelegram(api, project.id, "deals");
  setHealth(api, project.id);
  const publishing = api.addPublication({
    content_id: media.id,
    account_id: a.id,
  });
  api.startAttempt(api.publications.find((p) => p.id === publishing.id)!);
  const published = api.addPublication({
    content_id: media.id,
    account_id: b.id,
    status: "published",
    published_at: "2026-10-05T11:00:00Z",
  });
  // An older Draft of another account: never inferred into the set.
  const c = addTelegram(api, project.id, "misc");
  setHealth(api, project.id);
  api.addPublication({ content_id: media.id, account_id: c.id });

  // Opened from the Media detail, so Back leaves the task.
  const router = createMemoryRouter(routes, {
    initialEntries: [
      `/p/${project.id}/library/${media.id}`,
      publishPath(project.id, media.id, [publishing.id, published.id]),
    ],
    initialIndex: 1,
  });
  render(<RouterProvider router={router} />);
  const results = await screen.findByRole("region", { name: "Results" });
  expect(
    within(results).getByText("1 published · 1 publishing"),
  ).toBeInTheDocument();
  expect(
    within(results).getByText(
      "Publishing continues in the background. Track it in Posts.",
    ),
  ).toBeInTheDocument();
  // A set without Drafts is a result page only.
  expect(
    screen.queryByRole("heading", { name: /Review|Still to finish/ }),
  ).toBeNull();

  api.succeedAttempt(publishing.id);
  expect(
    await within(results).findByText("2 published", undefined, {
      timeout: 3000,
    }),
  ).toBeInTheDocument();
  expect(getRequests(`/publications/${published.id}`)).toHaveLength(1);
  expect(getRequests(`/publications/${publishing.id}`).length).toBeGreaterThan(
    1,
  );

  // Back to the Media, then forward: the same members, from the URL alone.
  await act(() => router.navigate(-1));
  expect(router.state.location.pathname).toBe(
    `/p/${project.id}/library/${media.id}`,
  );
  await act(() => router.navigate(1));
  const again = await screen.findByRole("region", { name: "Results" });
  expect(within(again).getByText("2 published")).toBeInTheDocument();
  expect(urlPosts(router)).toBe(`${publishing.id},${published.id}`);
});

describe("Back to media", () => {
  function backTo() {
    return screen.getByRole("link", { name: "Back to media" });
  }

  function withFrom(value: string, posts?: number[]) {
    const path = publishPath(project.id, media.id, posts);
    return `${path}${posts === undefined ? "?" : "&"}from=${encodeURIComponent(value)}`;
  }

  it.each([
    ["all", "all"],
    ["unsorted?sort=oldest", "unsorted"],
    [
      "folders/12?q=cafe+verano&type=videos&usage=unused&imported=30d&sort=name-asc",
      "folders/12",
    ],
  ])("N13: from=%j returns to that view and query", async (from, view) => {
    setHealth(api, project.id);
    await openPublish(withFrom(from));
    const query = from.includes("?") ? from.slice(from.indexOf("?")) : "";
    expect(backTo()).toHaveAttribute(
      "href",
      `/p/${project.id}/library/${view}/${media.id}${query}`,
    );
  });

  it("rebuilds the query instead of trusting it", async () => {
    setHealth(api, project.id);
    await openPublish(withFrom("all?evil=1&type=gif&q=x"));
    expect(backTo()).toHaveAttribute(
      "href",
      `/p/${project.id}/library/all/${media.id}?q=x`,
    );
  });

  it("keeps from when ?posts= is written, and after a reload", async () => {
    const account = addTelegram(api, project.id, "news");
    setHealth(api, project.id);
    const draft = api.addPublication({
      content_id: media.id,
      account_id: account.id,
    });
    const from = "unsorted?q=summer";
    const { router } = await openPublish(withFrom(from));

    await screen.findByRole("heading", { level: 2, name: "Review" });
    expect(urlPosts(router)).toBe(`${draft.id}`);
    expect(new URLSearchParams(router.state.location.search).get("from")).toBe(
      from,
    );
    const expected = `/p/${project.id}/library/unsorted/${media.id}?q=summer`;
    expect(backTo()).toHaveAttribute("href", expected);

    // A reload (or a new tab) of the same URL keeps the way back.
    const url = router.state.location.pathname + router.state.location.search;
    cleanup();
    await openPublish(url);
    expect(backTo()).toHaveAttribute("href", expected);
  });

  it.each([
    null,
    "//evil.com",
    "https://x",
    "/p/2/library/all",
    `/p/${2}/library/folders/3`,
    "folders/abc",
    "folders/0",
    "../posts",
    "javascript:alert(1)",
  ])(
    "N14: without a valid from (%j) goes to the detail over All media",
    async (from) => {
      setHealth(api, project.id);
      await openPublish(
        from === null ? publishPath(project.id, media.id) : withFrom(from),
      );
      expect(backTo()).toHaveAttribute(
        "href",
        `/p/${project.id}/library/${media.id}`,
      );
    },
  );
});
