import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { routes } from "../../routes.tsx";
import { FakeApi } from "../../test-fake-api.ts";
import type { Project, Publication } from "../../types.ts";
import {
  AUTOMATION_POLL_INTERVAL_MS,
  formatWhen,
  toDateTimeLocalValue,
} from "../../utils.ts";
import { setHealth, setViewport, writes } from "../publish/test-publish.ts";
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
  vi.useRealTimers();
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
  // The missing week is written by an effect right after the first render.
  await waitFor(() => expect(week(router)).toBe(dayKey(monday)));
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

// --- Quick Reschedule (Feature 024, checkpoint B) ------------------------------

/** A past week (the FakeApi's attempt times fall on its Monday) and a future one. */
const PAST_MONDAY = new Date(2026, 9, 5);
const FUTURE_MONDAY = new Date(2099, 0, 5);
const on = (monday: Date, day: number, hour: number) =>
  new Date(
    monday.getFullYear(),
    monday.getMonth(),
    monday.getDate() + day,
    hour,
  ).toISOString();

function addPost(title: string, values: Partial<Publication> = {}) {
  const content = api.addContent({ project_id: project.id, title });
  const account = api.addAccount({
    project_id: project.id,
    platform: "youtube",
    handle: title.toLowerCase().replace(/\W+/g, "-"),
  });
  return api.addPublication({
    content_id: content.id,
    account_id: account.id,
    ...values,
  });
}

function record(post: Publication) {
  return api.publications.find((item) => item.id === post.id)!;
}

async function openWeek(monday: Date) {
  const opened = open(
    `/p/${project.id}/posts?view=calendar&week=${dayKey(monday)}`,
  );
  const calendar = await screen.findByRole("region", { name: /^Week of/ });
  return { ...opened, calendar };
}

function daySection(date: string): HTMLElement {
  const heading = document.getElementById(
    `calendar-day-${dayKey(new Date(date))}`,
  )!;
  return heading.closest("section")!;
}

function patches() {
  return writes(api).filter((request) => request.method === "PATCH");
}

function overviews() {
  return api.requests.filter(
    (request) =>
      request.method === "GET" &&
      request.path === `/overview?project_id=${project.id}`,
  ).length;
}

function blockedPosts() {
  addPost("Published one", {
    status: "published",
    scheduled_at: on(PAST_MONDAY, 1, 9),
    published_at: on(PAST_MONDAY, 1, 9),
  });
  const publishing = addPost("Publishing one", {
    scheduled_at: on(PAST_MONDAY, 2, 9),
    auto_publish_enabled: true,
  });
  api.startAttempt(record(publishing), "scheduled");
  const review = addPost("Review one", {
    scheduled_at: on(PAST_MONDAY, 3, 9),
    auto_publish_enabled: true,
  });
  api.startAttempt(record(review), "scheduled");
  api.failAttempt(review.id, "timeout", "No answer.", false);
  addPost("Action one", { status: "awaiting_user_action" });
}

it.each([
  ["the week view", 1440],
  ["the agenda", null],
])(
  "in %s only Scheduled, Missed and Failed Posts have a schedule control, next to their link",
  async (_, width) => {
    if (width !== null) {
      setViewport(width);
    }
    addPost("Missed one", {
      scheduled_at: on(PAST_MONDAY, 4, 9),
      auto_publish_enabled: true,
    });
    addPost("Failed one", {
      status: "failed",
      scheduled_at: on(PAST_MONDAY, 5, 9),
    });
    blockedPosts();
    addPost("Automatic one", {
      scheduled_at: on(FUTURE_MONDAY, 1, 9),
      auto_publish_enabled: true,
    });
    addPost("Manual one", { scheduled_at: on(FUTURE_MONDAY, 2, 9) });

    const { calendar } = await openWeek(PAST_MONDAY);
    const controls = within(calendar).getAllByRole("button", {
      name: /^(Edit schedule|Reschedule): /,
    });
    expect(
      controls.map((control) => control.getAttribute("aria-label")),
    ).toEqual(["Reschedule: Missed one", "Reschedule: Failed one"]);
    for (const title of [
      "Published one",
      "Publishing one",
      "Review one",
      "Action one",
    ]) {
      const link = within(calendar).getByRole("link", {
        name: new RegExp(title),
      });
      expect(link.parentElement!.querySelector("button")).toBeNull();
    }
    for (const control of controls) {
      // A sibling of the link (never nested in it), after it in tab order.
      expect(control.closest("a")).toBeNull();
      expect(control.previousElementSibling?.tagName).toBe("A");
      if (width === null) {
        expect(control).toHaveTextContent("Reschedule");
      } else {
        expect(control).toHaveClass("ap-icon-button");
      }
    }
    cleanup();

    const future = await openWeek(FUTURE_MONDAY);
    expect(
      within(future.calendar)
        .getAllByRole("button", { name: /^(Edit schedule|Reschedule): / })
        .map((control) => control.getAttribute("aria-label")),
    ).toEqual(["Edit schedule: Automatic one", "Edit schedule: Manual one"]);
  },
);

it("Edit schedule of a future Post preloads its date; Cancel sends nothing", async () => {
  const date = on(FUTURE_MONDAY, 1, 18);
  addPost("Automatic one", { scheduled_at: date, auto_publish_enabled: true });
  const { calendar, user } = await openWeek(FUTURE_MONDAY);
  await user.click(
    within(calendar).getByRole("button", {
      name: "Edit schedule: Automatic one",
    }),
  );
  const dialog = await screen.findByRole("dialog", { name: "Edit schedule" });
  expect(within(dialog).getByLabelText(/Date and time/)).toHaveValue(
    toDateTimeLocalValue(date),
  );
  expect(writes(api)).toEqual([]);
  await user.click(within(dialog).getByRole("button", { name: "Cancel" }));
  expect(screen.queryByRole("dialog")).toBeNull();
  expect(writes(api)).toEqual([]);
});

it("Edit schedule of a Post whose time just passed opens empty", async () => {
  const date = new Date(Date.now() - 2 * 60 * 1000).toISOString();
  addPost("Due one", { scheduled_at: date, auto_publish_enabled: true });
  const { calendar, user } = await openWeek(mondayOf(new Date(date)));
  await user.click(
    within(calendar).getByRole("button", { name: "Edit schedule: Due one" }),
  );
  const dialog = await screen.findByRole("dialog", { name: "Edit schedule" });
  expect(within(dialog).getByLabelText(/Date and time/)).toHaveValue("");
});

it.each([
  [
    "Missed",
    { scheduled_at: on(PAST_MONDAY, 4, 9), auto_publish_enabled: true },
  ],
  ["Failed", { status: "failed", scheduled_at: on(PAST_MONDAY, 5, 9) }],
] as const)("Reschedule of a %s Post opens empty", async (title, values) => {
  addPost(title, values);
  const { calendar, user } = await openWeek(PAST_MONDAY);
  await user.click(
    within(calendar).getByRole("button", { name: `Reschedule: ${title}` }),
  );
  const dialog = await screen.findByRole("dialog", { name: "Reschedule" });
  expect(within(dialog).getByLabelText(/Date and time/)).toHaveValue("");
  expect(writes(api)).toEqual([]);
});

it("a manual schedule becomes automatic through Edit schedule", async () => {
  const post = addPost("Manual one", { scheduled_at: on(FUTURE_MONDAY, 2, 9) });
  const { calendar, user } = await openWeek(FUTURE_MONDAY);
  await user.click(
    within(calendar).getByRole("button", { name: "Edit schedule: Manual one" }),
  );
  const dialog = await screen.findByRole("dialog", { name: "Edit schedule" });
  const next = on(FUTURE_MONDAY, 2, 11);
  fireEvent.change(within(dialog).getByLabelText(/Date and time/), {
    target: { value: toDateTimeLocalValue(next) },
  });
  await user.click(
    within(dialog).getByRole("button", { name: "Edit schedule" }),
  );
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  expect(patches()).toEqual([
    {
      method: "PATCH",
      path: `/publications/${post.id}`,
      body: { scheduled_at: next, auto_publish_enabled: true },
    },
  ]);
  expect(
    await within(calendar).findByText("Scheduled · automatic"),
  ).toBeInTheDocument();
});

it("Edit schedule while automation is paused warns, confirms and stays paused", async () => {
  api.automation.paused = true;
  addPost("Paused one", {
    scheduled_at: on(FUTURE_MONDAY, 1, 9),
    auto_publish_enabled: true,
  });
  const { calendar, user } = await openWeek(FUTURE_MONDAY);
  expect(within(calendar).getByText("Scheduled · paused")).toBeInTheDocument();
  await user.click(
    within(calendar).getByRole("button", { name: "Edit schedule: Paused one" }),
  );
  const dialog = await screen.findByRole("dialog", { name: "Edit schedule" });
  expect(within(dialog).getByText(/Automation is paused/)).toBeInTheDocument();
  fireEvent.change(within(dialog).getByLabelText(/Date and time/), {
    target: { value: toDateTimeLocalValue(on(FUTURE_MONDAY, 3, 9)) },
  });
  await user.click(
    within(dialog).getByRole("button", { name: "Edit schedule" }),
  );
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  expect(patches()).toHaveLength(1);
  const moved = daySection(on(FUTURE_MONDAY, 3, 9));
  expect(await within(moved).findByText("Paused one")).toBeInTheDocument();
  expect(within(moved).getByText("Scheduled · paused")).toBeInTheDocument();
});

it("after confirming, the Post is on its new day and nowhere else; another week no longer shows it", async () => {
  setViewport(1440);
  const from = on(FUTURE_MONDAY, 1, 18);
  const to = on(FUTURE_MONDAY, 3, 18);
  addPost("Moving one", { scheduled_at: from, auto_publish_enabled: true });
  const { calendar, user } = await openWeek(FUTURE_MONDAY);
  expect(within(daySection(from)).getByText("Moving one")).toBeInTheDocument();

  await user.click(
    within(calendar).getByRole("button", { name: "Edit schedule: Moving one" }),
  );
  const dialog = await screen.findByRole("dialog", { name: "Edit schedule" });
  fireEvent.change(within(dialog).getByLabelText(/Date and time/), {
    target: { value: toDateTimeLocalValue(to) },
  });
  await user.click(
    within(dialog).getByRole("button", { name: "Edit schedule" }),
  );

  expect(
    await within(daySection(to)).findByText("Moving one"),
  ).toBeInTheDocument();
  expect(within(daySection(from)).queryByText("Moving one")).toBeNull();
  expect(within(calendar).getAllByText("Moving one")).toHaveLength(1);

  // Moved to the next week: it leaves the visible one.
  await user.click(
    within(calendar).getByRole("button", { name: "Edit schedule: Moving one" }),
  );
  const again = await screen.findByRole("dialog", { name: "Edit schedule" });
  fireEvent.change(within(again).getByLabelText(/Date and time/), {
    target: { value: toDateTimeLocalValue(on(FUTURE_MONDAY, 8, 18)) },
  });
  await user.click(
    within(again).getByRole("button", { name: "Edit schedule" }),
  );
  await waitFor(() =>
    expect(within(calendar).queryByText("Moving one")).toBeNull(),
  );
});

it("a 409 (the Post started meanwhile) keeps the dialog with its message and reloads the list", async () => {
  const post = addPost("Racing one", {
    scheduled_at: on(FUTURE_MONDAY, 1, 18),
    auto_publish_enabled: true,
  });
  const { calendar, user } = await openWeek(FUTURE_MONDAY);
  await user.click(
    within(calendar).getByRole("button", { name: "Edit schedule: Racing one" }),
  );
  const dialog = await screen.findByRole("dialog", { name: "Edit schedule" });
  api.startAttempt(record(post), "scheduled");
  api.failRequest("PATCH", `/publications/${post.id}`, 409, {
    error: {
      code: "publication_not_editable",
      message: "This publication is being published and cannot be changed.",
    },
  });
  await user.click(
    within(dialog).getByRole("button", { name: "Edit schedule" }),
  );

  expect(await within(dialog).findByRole("alert")).toHaveTextContent(
    "This publication is being published",
  );
  expect(screen.getByRole("dialog", { name: "Edit schedule" })).toBe(dialog);
  // The list behind the dialog shows the real state.
  await waitFor(() =>
    expect(
      within(daySection(on(FUTURE_MONDAY, 1, 18))).getByText("Publishing"),
    ).toBeInTheDocument(),
  );
});

it("a 422 keeps the dialog with its message and reloads the list", async () => {
  const post = addPost("Late one", {
    scheduled_at: on(FUTURE_MONDAY, 1, 18),
    auto_publish_enabled: true,
  });
  const { calendar, user } = await openWeek(FUTURE_MONDAY);
  await user.click(
    within(calendar).getByRole("button", { name: "Edit schedule: Late one" }),
  );
  const dialog = await screen.findByRole("dialog", { name: "Edit schedule" });
  const lists = () =>
    api.requests.filter(
      (request) => request.path === `/projects/${project.id}/publications`,
    ).length;
  const before = lists();
  api.failRequest("PATCH", `/publications/${post.id}`, 422, {
    error: {
      code: "validation_error",
      message: "Choose a date and time in the future.",
    },
  });
  await user.click(
    within(dialog).getByRole("button", { name: "Edit schedule" }),
  );
  expect(await within(dialog).findByRole("alert")).toHaveTextContent(
    "Choose a date and time in the future.",
  );
  await waitFor(() => expect(lists()).toBe(before + 1));
  expect(screen.getByRole("dialog", { name: "Edit schedule" })).toBe(dialog);
});

it.each([
  [
    "Edit schedule",
    { scheduled_at: on(FUTURE_MONDAY, 1, 18), auto_publish_enabled: true },
    FUTURE_MONDAY,
  ],
  [
    "Reschedule",
    { status: "failed", scheduled_at: on(PAST_MONDAY, 5, 9) },
    PAST_MONDAY,
  ],
] as const)(
  "a successful %s reads the project overview again exactly once",
  async (action, values, monday) => {
    addPost("Next one", values);
    const { calendar, user } = await openWeek(monday);
    await waitFor(() => expect(overviews()).toBeGreaterThan(0));
    await user.click(
      within(calendar).getByRole("button", { name: `${action}: Next one` }),
    );
    const dialog = await screen.findByRole("dialog", { name: action });
    const before = overviews();
    fireEvent.change(within(dialog).getByLabelText(/Date and time/), {
      target: { value: toDateTimeLocalValue(on(FUTURE_MONDAY, 2, 10)) },
    });
    await user.click(within(dialog).getByRole("button", { name: action }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    await waitFor(() => expect(overviews()).toBe(before + 1));
    // Settled: no further overview read.
    await act(async () => {});
    expect(overviews()).toBe(before + 1);
  },
);

it("a poll with no change does not read the overview again", async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  addPost("Waiting one", {
    scheduled_at: on(FUTURE_MONDAY, 1, 18),
    auto_publish_enabled: true,
  });
  await openWeek(FUTURE_MONDAY);
  await waitFor(() => expect(overviews()).toBeGreaterThan(0));
  const lists = () =>
    api.requests.filter(
      (request) => request.path === `/projects/${project.id}/publications`,
    ).length;
  const before = { overviews: overviews(), lists: lists() };
  await act(() => vi.advanceTimersByTimeAsync(AUTOMATION_POLL_INTERVAL_MS * 2));
  expect(lists()).toBeGreaterThan(before.lists);
  expect(overviews()).toBe(before.overviews);
});

it("click and Enter on an item still open its detail", async () => {
  setViewport(1440);
  addPost("Automatic one", {
    scheduled_at: on(FUTURE_MONDAY, 1, 18),
    auto_publish_enabled: true,
  });
  const { calendar, user } = await openWeek(FUTURE_MONDAY);
  const link = within(calendar).getByRole("link", { name: /Automatic one/ });
  expect(link).toHaveAttribute("data-detail-id");
  await user.click(link);
  expect(
    await screen.findByRole("region", { name: "Post details" }),
  ).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Close" }));
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());

  within(calendar)
    .getByRole("link", { name: /Automatic one/ })
    .focus();
  await user.keyboard("{Enter}");
  expect(
    await screen.findByRole("region", { name: "Post details" }),
  ).toBeInTheDocument();
});

// --- Drag to another day (Feature 024, checkpoint C) ---------------------------

const DRAG_TYPE = "application/x-autopublisher-post";
/** Wednesday of FUTURE_MONDAY's week at noon: Monday and Tuesday have passed. */
const WEDNESDAY_NOON = new Date(2099, 0, 7, 12, 0);

function fakeTransfer() {
  // What a browser starts with when a link is dragged.
  const data = new Map([["text/uri-list", "http://localhost/p/1/posts/1"]]);
  return {
    data,
    effectAllowed: "all",
    dropEffect: "none",
    clearData: vi.fn(() => data.clear()),
    setData: vi.fn((type: string, value: string) => data.set(type, value)),
    getData: (type: string) => data.get(type) ?? "",
  };
}

function dayOf(monday: Date, day: number) {
  const date = new Date(monday);
  date.setDate(date.getDate() + day);
  return daySection(date.toISOString());
}

function dropStates() {
  return Array.from(document.querySelectorAll("section[data-drop]")).map(
    (section) => section.getAttribute("data-drop"),
  );
}

function assertNoDragFeedback() {
  expect(
    document.querySelector("[data-drop], [data-drop-over], [data-dragging]"),
  ).toBeNull();
  expect(screen.queryByText(/Can't move here/)).toBeNull();
}

async function weekWithDrag() {
  vi.useFakeTimers({ shouldAdvanceTime: true, now: WEDNESDAY_NOON });
  setViewport(1440);
  const post = addPost("Moving one", {
    scheduled_at: on(FUTURE_MONDAY, 3, 18), // Thursday 18:00
    auto_publish_enabled: true,
  });
  const opened = await openWeek(FUTURE_MONDAY);
  const link = () =>
    // Hidden too: behind an open dialog the page is aria-hidden.
    within(opened.calendar).getByRole("link", {
      name: /Moving one/,
      hidden: true,
    });
  return { ...opened, post, link };
}

it("dragging replaces the link data with the Post id and classifies every day of the week", async () => {
  const { post, link } = await weekWithDrag();
  expect(link()).toHaveAttribute("draggable", "true");
  const dataTransfer = fakeTransfer();

  fireEvent.dragStart(link(), { dataTransfer });

  expect(dataTransfer.clearData).toHaveBeenCalled();
  expect([...dataTransfer.data]).toEqual([[DRAG_TYPE, String(post.id)]]);
  expect(dataTransfer.effectAllowed).toBe("move");
  expect(link()).toHaveAttribute("data-dragging");
  // Mon, Tue passed; Wed 18:00 is still ahead; Thu is its own day.
  expect(dropStates()).toEqual([
    "invalid",
    "invalid",
    "valid",
    "source",
    "valid",
    "valid",
    "valid",
  ]);
});

it("a drop on a valid day opens Edit schedule with that day and the same time; only Confirm sends it", async () => {
  const { post, link, user, calendar } = await weekWithDrag();
  const dataTransfer = fakeTransfer();
  fireEvent.dragStart(link(), { dataTransfer });
  const saturday = dayOf(FUTURE_MONDAY, 5);

  // Allowed: the default is prevented.
  expect(fireEvent.dragOver(saturday, { dataTransfer })).toBe(false);
  expect(dataTransfer.dropEffect).toBe("move");
  expect(saturday).toHaveAttribute("data-drop-over");
  fireEvent.drop(saturday, { dataTransfer });
  fireEvent.dragEnd(link(), { dataTransfer });

  const dialog = await screen.findByRole("dialog", { name: "Edit schedule" });
  const target = on(FUTURE_MONDAY, 5, 18);
  expect(within(dialog).getByLabelText(/Date and time/)).toHaveValue(
    toDateTimeLocalValue(target),
  );
  expect(writes(api)).toEqual([]);
  assertNoDragFeedback();

  await user.click(
    within(dialog).getByRole("button", { name: "Edit schedule" }),
  );
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  expect(patches()).toEqual([
    {
      method: "PATCH",
      path: `/publications/${post.id}`,
      body: { scheduled_at: target, auto_publish_enabled: true },
    },
  ]);
  expect(
    await within(dayOf(FUTURE_MONDAY, 5)).findByText("Moving one"),
  ).toBeInTheDocument();
  expect(within(calendar).getAllByText("Moving one")).toHaveLength(1);
});

it("a drop on a passed day, on today after the time, or on its own day does nothing", async () => {
  const { link } = await weekWithDrag();
  // Today (Wednesday) at 09:00 has passed at noon.
  const early = addPost("Early one", {
    scheduled_at: on(FUTURE_MONDAY, 4, 9),
    auto_publish_enabled: true,
  });
  await act(() => vi.advanceTimersByTimeAsync(AUTOMATION_POLL_INTERVAL_MS));
  const earlyLink = await screen.findByRole("link", { name: /Early one/ });
  expect(early.id).toBeGreaterThan(0);

  for (const [source, day] of [
    [link, 1], // Tuesday: passed
    [() => earlyLink, 2], // today, 09:00 already passed
    [link, 3], // its own day
  ] as const) {
    const dataTransfer = fakeTransfer();
    fireEvent.dragStart(source(), { dataTransfer });
    const target = dayOf(FUTURE_MONDAY, day);
    const allowed = !fireEvent.dragOver(target, { dataTransfer });
    expect(allowed).toBe(day === 3); // only its own day accepts (a no-op)
    if (day !== 3) {
      expect(dataTransfer.dropEffect).toBe("none");
      expect(
        within(target).getByText(
          "Can't move here — that time has already passed.",
        ),
      ).toBeInTheDocument();
    }
    fireEvent.drop(target, { dataTransfer });
    fireEvent.dragEnd(source(), { dataTransfer });
    expect(screen.queryByRole("dialog")).toBeNull();
    assertNoDragFeedback();
  }
  expect(writes(api)).toEqual([]);
});

it("a drag ended without a drop (Escape, outside) clears every feedback", async () => {
  const { link } = await weekWithDrag();
  const dataTransfer = fakeTransfer();
  fireEvent.dragStart(link(), { dataTransfer });
  fireEvent.dragOver(dayOf(FUTURE_MONDAY, 1), { dataTransfer });
  expect(document.querySelector("[data-drop-over]")).not.toBeNull();

  fireEvent.dragEnd(link(), { dataTransfer });

  assertNoDragFeedback();
  expect(screen.queryByRole("dialog")).toBeNull();
  expect(writes(api)).toEqual([]);
});

it("only automatic schedules are draggable, and only in the week view", async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true, now: WEDNESDAY_NOON });
  setViewport(1440);
  api.automation.paused = false;
  addPost("Automatic one", {
    scheduled_at: on(FUTURE_MONDAY, 3, 18),
    auto_publish_enabled: true,
  });
  addPost("Manual one", { scheduled_at: on(FUTURE_MONDAY, 4, 18) });
  addPost("Missed one", {
    scheduled_at: on(FUTURE_MONDAY, 0, 9),
    auto_publish_enabled: true,
  });
  addPost("Failed one", {
    status: "failed",
    scheduled_at: on(FUTURE_MONDAY, 1, 9),
  });
  const { calendar } = await openWeek(FUTURE_MONDAY);
  const linkOf = (title: string) =>
    within(calendar).getByRole("link", { name: new RegExp(title) });
  expect(linkOf("Automatic one")).toHaveAttribute("draggable", "true");
  for (const title of ["Manual one", "Missed one", "Failed one"]) {
    expect(linkOf(title)).not.toHaveAttribute("draggable");
    const dataTransfer = fakeTransfer();
    fireEvent.dragStart(linkOf(title), { dataTransfer });
    // The browser's own link drag is left alone.
    expect(dataTransfer.clearData).not.toHaveBeenCalled();
    expect(fireEvent.dragOver(dayOf(FUTURE_MONDAY, 5), { dataTransfer })).toBe(
      true,
    );
    assertNoDragFeedback();
  }
  // The schedule control is never draggable.
  for (const control of within(calendar).getAllByRole("button", {
    name: /^(Edit schedule|Reschedule): /,
  })) {
    expect(control).not.toHaveAttribute("draggable");
  }
  cleanup();

  // Agenda: nothing is draggable and days take no drop.
  setViewport(1279);
  const agenda = await openWeek(FUTURE_MONDAY);
  const link = within(agenda.calendar).getByRole("link", {
    name: /Automatic one/,
  });
  expect(link).not.toHaveAttribute("draggable");
  const dataTransfer = fakeTransfer();
  fireEvent.dragStart(link, { dataTransfer });
  expect(dataTransfer.clearData).not.toHaveBeenCalled();
  assertNoDragFeedback();
});

it.each([
  [
    "its date changed",
    (id: number) => {
      api.publications.find((item) => item.id === id)!.scheduled_at = on(
        FUTURE_MONDAY,
        3,
        20,
      );
    },
  ],
  [
    "it started publishing",
    (id: number) =>
      api.startAttempt(
        api.publications.find((item) => item.id === id)!,
        "scheduled",
      ),
  ],
  [
    "it was deleted",
    (id: number) => {
      api.publications = api.publications.filter((item) => item.id !== id);
    },
  ],
])(
  "a drop is ignored when a poll shows the dragged Post changed: %s",
  async (_, change) => {
    const { post, link } = await weekWithDrag();
    const dataTransfer = fakeTransfer();
    fireEvent.dragStart(link(), { dataTransfer });
    const saturday = dayOf(FUTURE_MONDAY, 5);
    fireEvent.dragOver(saturday, { dataTransfer });

    change(post.id);
    await act(() => vi.advanceTimersByTimeAsync(AUTOMATION_POLL_INTERVAL_MS));
    await waitFor(assertNoDragFeedback);

    fireEvent.drop(saturday, { dataTransfer });
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(writes(api)).toEqual([]);
    assertNoDragFeedback();
  },
);

it("a draggable item still opens its detail on click and Enter, and keeps its attributes", async () => {
  const { link, user, post } = await weekWithDrag();
  expect(link()).toHaveAttribute("data-detail-id", String(post.id));
  await user.click(link());
  expect(
    await screen.findByRole("region", { name: "Post details" }),
  ).toBeInTheDocument();
  expect(link()).toHaveAttribute("aria-current", "true");
  await user.click(screen.getByRole("button", { name: "Close" }));
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());

  link().focus();
  await user.keyboard("{Enter}");
  expect(
    await screen.findByRole("region", { name: "Post details" }),
  ).toBeInTheDocument();
});

// --- Focus and announcements (Feature 024, checkpoint D) -----------------------

function rangeHeading() {
  return screen.getByRole("heading", { level: 2, name: /–/, hidden: true });
}

function status() {
  return document.querySelector(".ap-calendar [role=status]")!;
}

async function focusOn(element: Element) {
  await waitFor(() => expect(document.activeElement).toBe(element));
}

it("keyboard: Tab goes from a Post's link to its control; Enter and Space open the dialog; Escape returns to the control", async () => {
  setViewport(1440);
  addPost("Automatic one", {
    scheduled_at: on(FUTURE_MONDAY, 1, 18),
    auto_publish_enabled: true,
  });
  const { calendar, user } = await openWeek(FUTURE_MONDAY);
  const link = within(calendar).getByRole("link", { name: /Automatic one/ });
  const control = within(calendar).getByRole("button", {
    name: "Edit schedule: Automatic one",
  });

  link.focus();
  await user.tab();
  expect(control).toHaveFocus();

  await user.keyboard("{Enter}");
  expect(
    await screen.findByRole("dialog", { name: "Edit schedule" }),
  ).toBeInTheDocument();
  await user.keyboard("{Escape}");
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  await focusOn(control);

  await user.keyboard(" ");
  const dialog = await screen.findByRole("dialog", { name: "Edit schedule" });
  await user.click(within(dialog).getByRole("button", { name: "Cancel" }));
  await focusOn(control);
  expect(status()).toHaveTextContent("");
  expect(writes(api)).toEqual([]);
});

it("drop → dialog → Cancel puts focus on the dragged Post's link", async () => {
  const { link, user } = await weekWithDrag();
  const source = link();
  const dataTransfer = fakeTransfer();
  fireEvent.dragStart(source, { dataTransfer });
  const saturday = dayOf(FUTURE_MONDAY, 5);
  fireEvent.dragOver(saturday, { dataTransfer });
  fireEvent.drop(saturday, { dataTransfer });
  fireEvent.dragEnd(source, { dataTransfer });

  const dialog = await screen.findByRole("dialog", { name: "Edit schedule" });
  await user.click(within(dialog).getByRole("button", { name: "Cancel" }));
  await focusOn(source);
  expect(status()).toHaveTextContent("");
});

it("a success inside the week focuses the Post on its new day and announces it", async () => {
  setViewport(1440);
  const post = addPost("Moving one", {
    scheduled_at: on(FUTURE_MONDAY, 1, 18),
    auto_publish_enabled: true,
  });
  const { calendar, user } = await openWeek(FUTURE_MONDAY);
  await user.click(
    within(calendar).getByRole("button", { name: "Edit schedule: Moving one" }),
  );
  const dialog = await screen.findByRole("dialog", { name: "Edit schedule" });
  const to = on(FUTURE_MONDAY, 3, 18);
  fireEvent.change(within(dialog).getByLabelText(/Date and time/), {
    target: { value: toDateTimeLocalValue(to) },
  });
  await user.click(
    within(dialog).getByRole("button", { name: "Edit schedule" }),
  );

  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  const moved = within(dayOf(FUTURE_MONDAY, 3)).getByRole("link", {
    name: /Moving one/,
  });
  expect(moved).toHaveAttribute("data-detail-id", String(post.id));
  await focusOn(moved);
  expect(status()).toHaveTextContent(
    `Moving one rescheduled for ${formatWhen(to)}.`,
  );
});

it("a success that moves the Post out of the week focuses the range heading", async () => {
  setViewport(1440);
  addPost("Leaving one", {
    scheduled_at: on(FUTURE_MONDAY, 1, 18),
    auto_publish_enabled: true,
  });
  const { calendar, user } = await openWeek(FUTURE_MONDAY);
  await user.click(
    within(calendar).getByRole("button", {
      name: "Edit schedule: Leaving one",
    }),
  );
  const dialog = await screen.findByRole("dialog", { name: "Edit schedule" });
  const to = on(FUTURE_MONDAY, 9, 18);
  fireEvent.change(within(dialog).getByLabelText(/Date and time/), {
    target: { value: toDateTimeLocalValue(to) },
  });
  await user.click(
    within(dialog).getByRole("button", { name: "Edit schedule" }),
  );

  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  expect(within(calendar).queryByText("Leaving one")).toBeNull();
  const heading = rangeHeading();
  expect(heading).toHaveAttribute("tabindex", "-1");
  await focusOn(heading);
  expect(status()).toHaveTextContent(
    `Leaving one rescheduled for ${formatWhen(to)}.`,
  );
});

it("when a 409 reload removes the control that opened the dialog, closing it focuses the range heading", async () => {
  setViewport(1440);
  const post = addPost("Racing one", {
    scheduled_at: on(FUTURE_MONDAY, 1, 18),
    auto_publish_enabled: true,
  });
  const { calendar, user } = await openWeek(FUTURE_MONDAY);
  const control = within(calendar).getByRole("button", {
    name: "Edit schedule: Racing one",
  });
  await user.click(control);
  const dialog = await screen.findByRole("dialog", { name: "Edit schedule" });
  api.startAttempt(record(post), "scheduled");
  api.failRequest("PATCH", `/publications/${post.id}`, 409, {
    error: {
      code: "publication_not_editable",
      message: "This publication is being published and cannot be changed.",
    },
  });
  await user.click(
    within(dialog).getByRole("button", { name: "Edit schedule" }),
  );
  expect(await within(dialog).findByRole("alert")).toBeInTheDocument();
  // The reload behind the dialog removes the control (now Publishing).
  await waitFor(() => expect(control.isConnected).toBe(false));

  await user.click(within(dialog).getByRole("button", { name: "Cancel" }));
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  await focusOn(rangeHeading());
  expect(document.activeElement).not.toBe(document.body);
  expect(status()).toHaveTextContent("");
});

it("Enter on an item opens its detail and closing it returns focus to the item", async () => {
  setViewport(1440);
  addPost("Automatic one", {
    scheduled_at: on(FUTURE_MONDAY, 1, 18),
    auto_publish_enabled: true,
  });
  const { calendar, user } = await openWeek(FUTURE_MONDAY);
  const link = within(calendar).getByRole("link", { name: /Automatic one/ });
  link.focus();
  await user.keyboard("{Enter}");
  expect(
    await screen.findByRole("region", { name: "Post details" }),
  ).toBeInTheDocument();
  await user.keyboard("{Escape}");
  await waitFor(() =>
    expect(screen.queryByRole("region", { name: "Post details" })).toBeNull(),
  );
  await focusOn(within(calendar).getByRole("link", { name: /Automatic one/ }));
});

it("agenda on a phone: a touch on the control opens a Sheet, nothing is draggable, Cancel returns focus", async () => {
  addPost("Missed one", {
    scheduled_at: on(PAST_MONDAY, 4, 9),
    auto_publish_enabled: true,
  });
  const { calendar, user } = await openWeek(PAST_MONDAY);
  expect(calendar).toHaveClass("ap-calendar-agenda");
  expect(calendar.querySelector("[draggable]")).toBeNull();
  const control = within(calendar).getByRole("button", {
    name: "Reschedule: Missed one",
  });
  await user.pointer({ keys: "[TouchA]", target: control });

  const dialog = await screen.findByRole("dialog", { name: "Reschedule" });
  expect(dialog).toHaveClass("ap-modal--sheet");
  await user.click(within(dialog).getByRole("button", { name: "Cancel" }));
  await focusOn(control);
});

// --- Reschedule highlight (Feature 026 T040/T041, contracts/ui.md §5) ---

/** The Calendar items that carry the highlight, by Post id. */
function landedIds(): number[] {
  return [
    ...document.querySelectorAll<HTMLElement>(
      ".ap-calendar-item[data-just-rescheduled]",
    ),
  ].map((item) => Number(item.dataset.detailId));
}

async function reschedule(
  user: ReturnType<typeof userEvent.setup>,
  title: string,
  to: string | null,
) {
  await user.click(
    screen.getByRole("button", { name: `Edit schedule: ${title}` }),
  );
  const dialog = await screen.findByRole("dialog", { name: "Edit schedule" });
  if (to !== null) {
    fireEvent.change(within(dialog).getByLabelText(/Date and time/), {
      target: { value: toDateTimeLocalValue(to) },
    });
  }
  return dialog;
}

async function confirm(
  user: ReturnType<typeof userEvent.setup>,
  dialog: HTMLElement,
) {
  await user.click(
    within(dialog).getByRole("button", { name: "Edit schedule" }),
  );
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
}

it.each([
  ["week view", 1440],
  ["agenda", 375],
])(
  "%s: a success inside the week highlights the Post on its new day only; focus and announcement unchanged",
  async (_view, width) => {
    setViewport(width);
    const post = addPost("Moving one", {
      scheduled_at: on(FUTURE_MONDAY, 1, 18),
      auto_publish_enabled: true,
    });
    addPost("Staying one", {
      scheduled_at: on(FUTURE_MONDAY, 3, 9),
      auto_publish_enabled: true,
    });
    const { user } = await openWeek(FUTURE_MONDAY);
    const to = on(FUTURE_MONDAY, 3, 18);

    await confirm(user, await reschedule(user, "Moving one", to));

    const moved = within(dayOf(FUTURE_MONDAY, 3)).getByRole("link", {
      name: /Moving one/,
    });
    expect(landedIds()).toEqual([post.id]);
    expect(moved).toHaveAttribute("data-just-rescheduled");
    // The same focus and announcement as before the feature (Feature 024).
    await focusOn(moved);
    expect(status()).toHaveTextContent(
      `Moving one rescheduled for ${formatWhen(to)}.`,
    );

    // Its badge's animations never clear it; its own end does.
    fireEvent.animationEnd(moved, { animationName: "ap-badge-emphasis" });
    fireEvent.animationEnd(moved, { animationName: "ap-pulse" });
    expect(moved).toHaveAttribute("data-just-rescheduled");
    fireEvent.animationEnd(moved, { animationName: "ap-highlight" });
    expect(landedIds()).toEqual([]);
    expect(document.activeElement).toBe(moved);
  },
);

it("a drop confirmed in the dialog highlights the Post on the target day; drag attributes unchanged", async () => {
  const { post, link } = await weekWithDrag();
  const dataTransfer = fakeTransfer();
  fireEvent.dragStart(link(), { dataTransfer });
  const saturday = dayOf(FUTURE_MONDAY, 5);
  fireEvent.dragOver(saturday, { dataTransfer });
  fireEvent.drop(saturday, { dataTransfer });
  fireEvent.dragEnd(link(), { dataTransfer });
  const dialog = await screen.findByRole("dialog", { name: "Edit schedule" });
  const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
  await confirm(user, dialog);

  expect(
    await within(dayOf(FUTURE_MONDAY, 5)).findByText("Moving one"),
  ).toBeInTheDocument();
  expect(landedIds()).toEqual([post.id]);
  assertNoDragFeedback();
  expect(link()).not.toHaveAttribute("data-dragging");
});

it.each([
  ["Cancel", "cancel"],
  ["a 409", 409],
  ["a 422", 422],
  ["the same date", "same"],
] as const)("no highlight after %s", async (_label, outcome) => {
  setViewport(1440);
  const post = addPost("Moving one", {
    scheduled_at: on(FUTURE_MONDAY, 1, 18),
    auto_publish_enabled: true,
  });
  const { user } = await openWeek(FUTURE_MONDAY);
  const dialog = await reschedule(
    user,
    "Moving one",
    outcome === "same" ? null : on(FUTURE_MONDAY, 3, 18),
  );
  if (outcome === "cancel") {
    await user.click(within(dialog).getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  } else if (typeof outcome === "number") {
    api.failRequest("PATCH", `/publications/${post.id}`, outcome, {
      error: { code: "conflict", message: "It cannot be changed now." },
    });
    await user.click(
      within(dialog).getByRole("button", { name: "Edit schedule" }),
    );
    expect(await within(dialog).findByRole("alert")).toBeInTheDocument();
  } else {
    await confirm(user, dialog);
    expect(patches()).toHaveLength(1);
  }
  expect(landedIds()).toEqual([]);
});

it("a Post moved out of the visible week is never highlighted, even on its new week", async () => {
  setViewport(1440);
  addPost("Leaving one", {
    scheduled_at: on(FUTURE_MONDAY, 1, 18),
    auto_publish_enabled: true,
  });
  const { user, router } = await openWeek(FUTURE_MONDAY);

  await confirm(
    user,
    await reschedule(user, "Leaving one", on(FUTURE_MONDAY, 9, 18)),
  );
  expect(landedIds()).toEqual([]);

  // By URL…
  const next = dayKey(new Date(on(FUTURE_MONDAY, 7, 0)));
  await act(() =>
    router.navigate(`/p/${project.id}/posts?view=calendar&week=${next}`),
  );
  expect(
    await within(dayOf(new Date(on(FUTURE_MONDAY, 7, 0)), 2)).findByText(
      "Leaving one",
    ),
  ).toBeInTheDocument();
  expect(landedIds()).toEqual([]);
  // …and by Back / Forward.
  await act(() => router.navigate(-1));
  await screen.findByRole("region", { name: /^Week of/ });
  await act(() => router.navigate(1));
  expect(await screen.findByText("Leaving one")).toBeInTheDocument();
  expect(landedIds()).toEqual([]);
});

it("leaving the week ends it: coming back shows no late highlight", async () => {
  setViewport(1440);
  const post = addPost("Moving one", {
    scheduled_at: on(FUTURE_MONDAY, 1, 18),
    auto_publish_enabled: true,
  });
  const { user, router } = await openWeek(FUTURE_MONDAY);
  await confirm(
    user,
    await reschedule(user, "Moving one", on(FUTURE_MONDAY, 3, 18)),
  );
  expect(landedIds()).toEqual([post.id]);

  await user.click(screen.getByRole("link", { name: "Next week" }));
  await waitFor(() => expect(week(router)).not.toBe(dayKey(FUTURE_MONDAY)));
  expect(landedIds()).toEqual([]);

  await act(() => router.navigate(-1));
  await waitFor(() => expect(week(router)).toBe(dayKey(FUTURE_MONDAY)));
  expect(
    await within(dayOf(FUTURE_MONDAY, 3)).findByText("Moving one"),
  ).toBeInTheDocument();
  expect(landedIds()).toEqual([]);
});

it("opening another dialog ends it", async () => {
  setViewport(1440);
  addPost("Moving one", {
    scheduled_at: on(FUTURE_MONDAY, 1, 18),
    auto_publish_enabled: true,
  });
  addPost("Other one", {
    scheduled_at: on(FUTURE_MONDAY, 4, 9),
    auto_publish_enabled: true,
  });
  const { user } = await openWeek(FUTURE_MONDAY);
  await confirm(
    user,
    await reschedule(user, "Moving one", on(FUTURE_MONDAY, 3, 18)),
  );
  expect(landedIds()).toHaveLength(1);

  const dialog = await reschedule(user, "Other one", null);
  expect(landedIds()).toEqual([]);
  await user.click(within(dialog).getByRole("button", { name: "Cancel" }));
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  expect(landedIds()).toEqual([]);
});
