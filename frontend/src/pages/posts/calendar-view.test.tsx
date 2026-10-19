import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { routes } from "../../routes.tsx";
import { FakeApi } from "../../test-fake-api.ts";
import type { Project } from "../../types.ts";
import { setHealth, setViewport } from "../publish/test-publish.ts";
import { dayKey, mondayOf } from "./calendar.ts";

let api: FakeApi;
let project: Project;
const monday = mondayOf(new Date());
const thisWeek = (day: number, hour: number) =>
  new Date(
    monday.getFullYear(),
    monday.getMonth(),
    monday.getDate() + day,
    hour,
  ).toISOString();

beforeEach(() => {
  api = new FakeApi();
  api.install();
  project = api.addProject({ name: "L4i4" });
  const media = api.addContent({ project_id: project.id, title: "Teaser" });
  let handle = 0;
  const account = () =>
    api.addAccount({
      project_id: project.id,
      platform: "youtube",
      handle: `c${(handle += 1)}`,
    }).id;
  api.addPublication({
    content_id: media.id,
    account_id: account(),
    scheduled_at: thisWeek(6, 18),
    auto_publish_enabled: true,
  });
  api.addPublication({
    content_id: media.id,
    account_id: account(),
    status: "published",
    scheduled_at: thisWeek(-10, 9),
    published_at: thisWeek(1, 9),
  });
  api.addPublication({ content_id: media.id, account_id: account() }); // a Draft
  api.addPublication({
    content_id: media.id,
    account_id: account(),
    status: "cancelled",
    scheduled_at: thisWeek(2, 9),
  });
  setHealth(api, project.id);
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function open(path: string) {
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  render(<RouterProvider router={router} />);
  return { router, user: userEvent.setup() };
}

function week(router: { state: { location: { search: string } } }) {
  return new URLSearchParams(router.state.location.search).get("week");
}

it("a missing week becomes the current one; next week is pushed and survives a reload", async () => {
  const { router, user } = open(`/p/${project.id}/posts?view=calendar`);
  await screen.findByRole("region", { name: /^Week of/ });
  expect(week(router)).toBe(dayKey(monday));
  expect(screen.getByText(/Times in /)).toBeInTheDocument();

  await user.click(screen.getByRole("link", { name: "Next week" }));
  const next = dayKey(
    new Date(monday.getFullYear(), monday.getMonth(), monday.getDate() + 7),
  );
  expect(week(router)).toBe(next);
  expect(await screen.findByText("No posts this week.")).toBeInTheDocument();
  cleanup();

  // A reload of that URL keeps the week.
  const reloaded = open(`/p/${project.id}/posts?view=calendar&week=${next}`);
  await screen.findByRole("region", { name: /^Week of/ });
  expect(week(reloaded.router)).toBe(next);
});

it("the agenda (no matchMedia) lists the days with Posts, never Drafts or Cancelled", async () => {
  open(`/p/${project.id}/posts?view=calendar&week=${dayKey(monday)}`);
  const calendar = await screen.findByRole("region", { name: /^Week of/ });
  expect(calendar).toHaveClass("ap-calendar-agenda");
  const items = within(calendar).getAllByRole("link");
  expect(items).toHaveLength(2);
  // Published on day 2 (its real time), then the scheduled one on Sunday.
  expect(items[0]).toHaveTextContent("Published");
  expect(items[1]).toHaveTextContent("Scheduled · automatic");
  expect(within(calendar).queryByText("Draft")).toBeNull();
  expect(within(calendar).queryByText("Cancelled")).toBeNull();
  expect(calendar.querySelector("[role=grid]")).toBeNull();
});

it("between 1024 and 1279 px the Calendar stays an agenda", async () => {
  setViewport(1279);
  open(`/p/${project.id}/posts?view=calendar&week=${dayKey(monday)}`);
  const calendar = await screen.findByRole("region", { name: /^Week of/ });
  expect(calendar).toHaveClass("ap-calendar-agenda");
});

it("the week view from 1280 px has one section per day; a Post opens its detail in a drawer and closing keeps the week", async () => {
  setViewport(1440);
  const path = `/p/${project.id}/posts?view=calendar&week=${dayKey(monday)}`;
  const { router, user } = open(path);
  const calendar = await screen.findByRole("region", { name: /^Week of/ });
  expect(calendar).toHaveClass("ap-calendar-week");
  expect(within(calendar).getAllByRole("heading", { level: 3 })).toHaveLength(
    7,
  );

  await user.click(within(calendar).getAllByRole("link")[0]);
  expect(router.state.location.search).toBe(
    `?view=calendar&week=${dayKey(monday)}`,
  );
  expect(
    await screen.findByRole("region", { name: "Post details" }),
  ).toBeInTheDocument();
  // A side panel would squeeze the seven columns: the detail is a drawer.
  expect(screen.getByRole("dialog")).toBeInTheDocument();
  expect(screen.queryByRole("complementary")).not.toBeInTheDocument();
  expect(document.querySelector("[data-week]")).toHaveClass("ap-calendar-week");
  await user.click(screen.getByRole("button", { name: "Close" }));
  expect(router.state.location.pathname).toBe(`/p/${project.id}/posts`);
  expect(router.state.location.search).toBe(
    `?view=calendar&week=${dayKey(monday)}`,
  );
  expect(screen.getByRole("region", { name: /^Week of/ })).toBeInTheDocument();
});
