import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { FakeApi } from "../../test-fake-api.ts";
import { AUTOMATION_POLL_INTERVAL_MS, POLL_INTERVAL_MS } from "../../utils.ts";
import { pollInterval, statesChanged, usePostsData } from "./usePostsData.ts";
import { post } from "./test-posts.ts";

let api: FakeApi;

beforeEach(() => {
  api = new FakeApi();
  api.install();
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

it.each([
  [
    "something publishing",
    [post("publishing"), post("draft")],
    POLL_INTERVAL_MS,
  ],
  [
    "an armed post waiting",
    [post("scheduled_automatic", { auto_publish_state: "waiting" })],
    AUTOMATION_POLL_INTERVAL_MS,
  ],
  [
    "nothing moving",
    [
      post("draft"),
      post("scheduled_manual", { auto_publish_state: "disabled" }),
    ],
    null,
  ],
])("polls by the data: %s", (_, posts, interval) => {
  expect(pollInterval(posts)).toBe(interval);
});

it("reloads the overview when a visible state changes, with a single poller", async () => {
  const project = api.addProject({ name: "L4i4" });
  const media = api.addContent({ project_id: project.id });
  const account = api.addAccount({
    project_id: project.id,
    platform: "youtube",
  });
  const created = api.addPublication({
    content_id: media.id,
    account_id: account.id,
  });
  api.startAttempt(
    api.publications.find((record) => record.id === created.id)!,
  );
  const onStatusChange = vi.fn();
  vi.useFakeTimers({ shouldAdvanceTime: true });

  const { result } = renderHook(() => usePostsData(project.id, onStatusChange));
  await waitFor(() => expect(result.current.posts).toHaveLength(1));
  expect(result.current.byId(created.id)?.display_state).toBe("publishing");

  api.succeedAttempt(created.id);
  await act(() => vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS));
  await waitFor(() =>
    expect(result.current.byId(created.id)?.display_state).toBe("published"),
  );
  expect(onStatusChange).toHaveBeenCalledTimes(1);
  const lists = () =>
    api.requests.filter(
      (request) => request.path === `/projects/${project.id}/publications`,
    ).length;
  const count = lists();
  // Nothing moves any more: no further polling.
  await act(() => vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS * 3));
  expect(lists()).toBe(count);
});

it.each([
  ["identical lists", "2026-10-30T17:30:00Z", "scheduled_automatic", false],
  [
    "the same instant written differently",
    "2026-10-30T17:30:00.000Z",
    "scheduled_automatic",
    false,
  ],
  [
    "only the date changed",
    "2026-10-31T17:30:00Z",
    "scheduled_automatic",
    true,
  ],
  ["only the state changed", "2026-10-30T17:30:00Z", "scheduled_paused", true],
] as const)("statesChanged: %s → %s", (_, date, state, changed) => {
  const before = [
    post("scheduled_automatic", {
      id: 1,
      scheduled_at: "2026-10-30T17:30:00Z",
    }),
  ];
  const after = [post(state, { id: 1, scheduled_at: date })];
  expect(statesChanged(before, after)).toBe(changed);
});

it("a reload that only changed a date reloads the overview once; an unchanged poll never does", async () => {
  const project = api.addProject({ name: "L4i4" });
  const media = api.addContent({ project_id: project.id });
  const account = api.addAccount({
    project_id: project.id,
    platform: "youtube",
  });
  const created = api.addPublication({
    content_id: media.id,
    account_id: account.id,
    scheduled_at: "2099-01-01T08:00:00Z",
    auto_publish_enabled: true,
  });
  const onStatusChange = vi.fn();
  vi.useFakeTimers({ shouldAdvanceTime: true });

  const { result } = renderHook(() => usePostsData(project.id, onStatusChange));
  await waitFor(() => expect(result.current.posts).toHaveLength(1));
  // An armed Post waiting: the list is polled, and nothing changes.
  await act(() => vi.advanceTimersByTimeAsync(AUTOMATION_POLL_INTERVAL_MS * 3));
  expect(onStatusChange).not.toHaveBeenCalled();

  api.publications.find((record) => record.id === created.id)!.scheduled_at =
    "2099-01-02T08:00:00Z";
  await act(() => result.current.reload());
  expect(result.current.byId(created.id)?.display_state).toBe(
    "scheduled_automatic",
  );
  expect(onStatusChange).toHaveBeenCalledTimes(1);

  await act(() => vi.advanceTimersByTimeAsync(AUTOMATION_POLL_INTERVAL_MS * 3));
  expect(onStatusChange).toHaveBeenCalledTimes(1);
});
