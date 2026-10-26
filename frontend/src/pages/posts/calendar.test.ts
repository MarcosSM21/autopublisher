import { describe, expect, it } from "vitest";
import {
  calendarMoment,
  dayKey,
  parseWeek,
  postsByDay,
  scheduleAction,
} from "./calendar.ts";
import { attempt, post } from "./test-posts.ts";

describe("calendarMoment", () => {
  it.each([
    [
      "Published uses published_at, never its old scheduled_at",
      post("published", {
        scheduled_at: "2026-10-01T10:00:00Z",
        published_at: "2026-10-03T12:00:00Z",
      }),
      "2026-10-03T12:00:00Z",
    ],
    [
      "Scheduled uses scheduled_at",
      post("scheduled_automatic", { scheduled_at: "2026-10-23T18:00:00Z" }),
      "2026-10-23T18:00:00Z",
    ],
    [
      "Publishing now (manual) of a Post scheduled for Friday is on Tuesday",
      post("publishing", {
        scheduled_at: "2026-10-23T18:00:00Z",
        latest_attempt: attempt({
          trigger: "manual",
          status: "running",
          started_at: "2026-10-20T09:00:00Z",
        }),
      }),
      "2026-10-20T09:00:00Z",
    ],
    [
      "Publishing started by the scheduler keeps scheduled_at",
      post("publishing", {
        scheduled_at: "2026-10-23T18:00:00Z",
        latest_attempt: attempt({
          trigger: "scheduled",
          status: "running",
          started_at: "2026-10-23T18:00:30Z",
        }),
      }),
      "2026-10-23T18:00:00Z",
    ],
    [
      "Publishing without an attempt falls back to updated_at",
      post("publishing", { updated_at: "2026-10-21T08:00:00Z" }),
      "2026-10-21T08:00:00Z",
    ],
    [
      "Missed uses scheduled_at",
      post("missed", { scheduled_at: "2026-10-18T10:00:00Z" }),
      "2026-10-18T10:00:00Z",
    ],
    [
      "Failed by the scheduler uses scheduled_at",
      post("failed", {
        scheduled_at: "2026-10-18T10:00:00Z",
        latest_attempt: attempt({
          trigger: "scheduled",
          started_at: "2026-10-18T10:00:20Z",
        }),
      }),
      "2026-10-18T10:00:00Z",
    ],
    [
      "Failed manually uses the attempt start",
      post("needs_review", {
        scheduled_at: "2026-10-25T10:00:00Z",
        latest_attempt: attempt({
          trigger: "manual",
          started_at: "2026-10-19T07:00:00Z",
        }),
      }),
      "2026-10-19T07:00:00Z",
    ],
    [
      "Needs action uses when the delivery finished",
      post("needs_action", {
        latest_attempt: attempt({ finished_at: "2026-10-19T08:30:00Z" }),
      }),
      "2026-10-19T08:30:00Z",
    ],
    ["Drafts are never shown", post("draft"), null],
    [
      "Cancelled are never shown",
      post("cancelled", { scheduled_at: "2026-10-20T10:00:00Z" }),
      null,
    ],
  ])("%s", (_, candidate, expected) => {
    expect(calendarMoment(candidate)).toBe(expected);
  });
});

describe("parseWeek", () => {
  const today = new Date(2026, 9, 21); // Wednesday 21 Oct 2026
  it.each([
    ["2026-10-19", "2026-10-19", true],
    ["2026-10-25", "2026-10-19", false], // a Sunday: the week of the Monday before
    ["2026-02-30", "2026-10-19", false],
    ["next-week", "2026-10-19", false],
    [null, "2026-10-19", false],
    ["2026-10-26", "2026-10-26", true],
  ])("%j → %s (valid: %s)", (param, monday, valid) => {
    const result = parseWeek(param, today);
    expect(dayKey(result.monday)).toBe(monday);
    expect(result.valid).toBe(valid);
  });
});

it("puts each shown Post on its local day, by time", () => {
  const monday = new Date(2026, 9, 19);
  const late = post("scheduled_automatic", {
    id: 1,
    scheduled_at: new Date(2026, 9, 20, 18).toISOString(),
  });
  const early = post("published", {
    id: 2,
    published_at: new Date(2026, 9, 20, 9).toISOString(),
  });
  const outside = post("scheduled_automatic", {
    id: 3,
    scheduled_at: new Date(2026, 9, 27, 9).toISOString(),
  });
  const days = postsByDay(
    [late, early, outside, post("draft", { id: 4 })],
    monday,
  );
  expect(days).toHaveLength(7);
  expect(days[1].posts.map((item) => item.post.id)).toEqual([2, 1]);
  expect(days.flatMap((day) => day.posts)).toHaveLength(2);
});

describe("scheduleAction", () => {
  it.each([
    ["scheduled_automatic", "edit_schedule"],
    ["scheduled_paused", "edit_schedule"],
    ["scheduled_manual", "edit_schedule"],
    ["missed", "reschedule"],
    ["failed", "reschedule"],
    ["needs_review", null],
    ["needs_action", null],
    ["publishing", null],
    ["published", null],
    ["draft", null],
    ["cancelled", null],
  ] as const)("%s → %s", (state, action) => {
    expect(scheduleAction(post(state))).toBe(action);
  });
});
