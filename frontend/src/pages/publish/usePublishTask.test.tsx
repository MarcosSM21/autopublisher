import { describe, expect, it, vi } from "vitest";
import { ApiError } from "../../api.ts";
import type { PostDisplayState, Publication } from "../../types.ts";
import {
  initialTaskState,
  postsSearch,
  selectMembers,
  taskReducer,
  type TaskState,
} from "./usePublishTask.ts";

const common = { description: "Caption", hashtags: "#a" };

function post(id: number, display_state: PostDisplayState = "draft") {
  return { id, account_id: id * 10, display_state } as Publication;
}

function composing(): TaskState {
  return taskReducer(initialTaskState(), {
    type: "members_loaded",
    posts: [],
    notice: null,
    common,
  });
}

it("composing → creating → task, focusing Review once", () => {
  let state = composing();
  expect(state.phase).toBe("composing");
  expect(state.compose.common).toEqual(common);
  state = taskReducer(state, {
    type: "compose_change",
    changes: { selected: [10, 20] },
  });
  state = taskReducer(state, { type: "create_start" });
  expect(state.phase).toBe("creating");
  state = taskReducer(state, { type: "created", posts: [post(1), post(2)] });
  expect(state.phase).toBe("task");
  expect(state.focusReview).toBe(true);
  expect(selectMembers(state, [1, 2]).review.map((item) => item.id)).toEqual([
    1, 2,
  ]);
  expect(taskReducer(state, { type: "focus_done" }).focusReview).toBe(false);
});

it("creating → composing on a 4xx keeps every input", () => {
  let state = composing();
  state = taskReducer(state, {
    type: "compose_change",
    changes: {
      selected: [10],
      common: { description: "Mine", hashtags: "" },
      custom: { 10: { description: "Custom" } },
    },
  });
  state = taskReducer(state, { type: "create_start" });
  const error = new ApiError(409, "duplicate", "Already has a post.");
  state = taskReducer(state, { type: "create_failed", error });
  expect(state.phase).toBe("composing");
  expect(state.compose).toMatchObject({
    selected: [10],
    common: { description: "Mine", hashtags: "" },
    custom: { 10: { description: "Custom" } },
    createError: error,
  });
});

it("re-partitions when a member changes, in URL order", () => {
  let state = taskReducer(initialTaskState(), {
    type: "members_loaded",
    posts: [post(1), post(2), post(3, "published")],
    notice: null,
    common,
  });
  expect(state.phase).toBe("task");
  const before = selectMembers(state, [3, 1, 2]);
  expect(before.review.map((item) => item.id)).toEqual([1, 2]);
  expect(before.results.map((item) => item.id)).toEqual([3]);

  state = taskReducer(state, {
    type: "post_updated",
    post: post(2, "publishing"),
  });
  const after = selectMembers(state, [3, 1, 2]);
  expect(after.review.map((item) => item.id)).toEqual([1]);
  expect(after.results.map((item) => item.id)).toEqual([3, 2]);
});

it("remembers a removed Post by account, and stays in the task when the set empties", () => {
  let state = taskReducer(initialTaskState(), {
    type: "members_loaded",
    posts: [post(1)],
    notice: null,
    common,
  });
  state = taskReducer(state, {
    type: "post_removed",
    post: post(1, "cancelled"),
  });
  expect(state.removed).toEqual({ 10: 1 });
  state = taskReducer(state, {
    type: "members_loaded",
    posts: [],
    notice: null,
    common,
  });
  expect(state.phase).toBe("task");
});

it.each([
  [[14, 12], "", "?posts=14,12"],
  [[3], "?posts=1&from=all%3Fq%3Dx", "?posts=3&from=all%3Fq%3Dx"],
  // Only `from` is carried: stale or unknown params are dropped.
  [[3], "?junk=1&posts=1&from=unsorted", "?posts=3&from=unsorted"],
  [[3], "?posts=1&junk=1", "?posts=3"],
])(
  "postsSearch(%j, %j) keeps only posts and from",
  (ids, current, expected) => {
    expect(postsSearch(ids, current)).toBe(expected);
  },
);

describe("Published emphasis context (Feature 026)", () => {
  function published(): TaskState {
    let state = taskReducer(composing(), {
      type: "created",
      posts: [post(1), post(2)],
    });
    state = taskReducer(state, { type: "run_start", run: "now", ids: [1, 2] });
    for (const id of [1, 2]) {
      state = taskReducer(state, {
        type: "run_event",
        id,
        post: post(id, "published"),
        error: null,
      });
    }
    return state;
  }

  it("emphasis_shown marks only that Post, and an unknown id is a no-op", () => {
    const setItem = vi.spyOn(Storage.prototype, "setItem");
    let state = published();
    state = taskReducer(state, { type: "emphasis_shown", id: 1 });
    expect(state.steps[1].emphasized).toBe(true);
    expect(state.steps[2].emphasized).toBeUndefined();
    expect(taskReducer(state, { type: "emphasis_shown", id: 1 })).toBe(state);
    expect(taskReducer(state, { type: "emphasis_shown", id: 99 })).toBe(state);
    expect(setItem).not.toHaveBeenCalled();
    setItem.mockRestore();
  });

  it("run_start begins a new operation: every Post is eligible again", () => {
    let state = taskReducer(published(), { type: "emphasis_shown", id: 1 });
    state = taskReducer(state, { type: "run_start", run: "now", ids: [1] });
    expect(state.steps).toEqual({
      1: { run: "now", status: "running", message: null },
    });
  });
});
