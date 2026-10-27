import { afterEach, describe, expect, it, vi } from "vitest";
import {
  calendarMoment,
  canDrag,
  dayKey,
  moveToDay,
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

describe("canDrag", () => {
  it.each([
    ["scheduled_automatic", true],
    ["scheduled_paused", true],
    ["scheduled_manual", false],
    ["missed", false],
    ["failed", false],
    ["needs_review", false],
    ["needs_action", false],
    ["publishing", false],
    ["published", false],
    ["draft", false],
    ["cancelled", false],
  ] as const)("%s → %s", (state, draggable) => {
    expect(canDrag(post(state))).toBe(draggable);
  });
});

describe("moveToDay", () => {
  /** A local wall-clock instant as an ISO string. */
  const local = (
    year: number,
    month: number,
    day: number,
    hour = 0,
    minute = 0,
  ) => new Date(year, month - 1, day, hour, minute).toISOString();
  const day = (year: number, month: number, date: number) =>
    new Date(year, month - 1, date);
  // Tuesday 27 Oct 2026, 18:30 local; "now" is that Monday at noon.
  const tuesday = local(2026, 10, 27, 18, 30);
  const monday = new Date(2026, 9, 26, 12, 0);

  it("the same day is the source", () => {
    expect(moveToDay(tuesday, day(2026, 10, 27), monday).kind).toBe("source");
  });

  it("another day keeps the local hour and minute", () => {
    const move = moveToDay(tuesday, day(2026, 10, 29), monday);
    expect(move.kind).toBe("valid");
    expect(move.at).toBe(local(2026, 10, 29, 18, 30));
  });

  it("an earlier day of a past week is invalid, of a future week valid", () => {
    const friday = local(2026, 10, 30, 9, 0);
    const fridayNoon = new Date(2026, 9, 30, 12, 0);
    expect(moveToDay(friday, day(2026, 10, 26), fridayNoon).kind).toBe(
      "invalid",
    );
    expect(moveToDay(friday, day(2026, 11, 2), fridayNoon)).toEqual({
      at: local(2026, 11, 2, 9, 0),
      kind: "valid",
    });
  });

  it("crosses a month and a year", () => {
    expect(
      moveToDay(local(2026, 10, 30, 7, 15), day(2026, 11, 2), monday),
    ).toEqual({ at: local(2026, 11, 2, 7, 15), kind: "valid" });
    expect(
      moveToDay(local(2026, 12, 31, 23, 45), day(2027, 1, 1), monday),
    ).toEqual({ at: local(2027, 1, 1, 23, 45), kind: "valid" });
  });

  it("today is valid only while the original time is still ahead", () => {
    const thursday = local(2026, 10, 29, 9, 0);
    const today = day(2026, 10, 27);
    expect(moveToDay(thursday, today, new Date(2026, 9, 27, 10, 0)).kind).toBe(
      "invalid",
    );
    expect(moveToDay(thursday, today, new Date(2026, 9, 27, 8, 0)).kind).toBe(
      "valid",
    );
    // Exactly now is not in the future.
    expect(moveToDay(thursday, today, new Date(2026, 9, 27, 9, 0)).kind).toBe(
      "invalid",
    );
  });

  describe("across a daylight saving change (Europe/Madrid)", () => {
    afterEach(() => {
      vi.unstubAllEnvs();
    });

    it("a time that does not exist is the browser's normalized one", () => {
      vi.stubEnv("TZ", "Europe/Madrid");
      // 29 Mar 2026: 02:00 → 03:00, so 02:30 does not exist that day.
      const saturday = local(2026, 3, 28, 2, 30);
      const move = moveToDay(saturday, day(2026, 3, 29), new Date(2026, 2, 1));
      expect(move.kind).toBe("valid");
      const moved = new Date(move.at);
      expect([moved.getDate(), moved.getHours(), moved.getMinutes()]).toEqual([
        29, 3, 30,
      ]);
    });

    it("an ambiguous time on the fall-back day gives a valid instant", () => {
      vi.stubEnv("TZ", "Europe/Madrid");
      // 25 Oct 2026: 03:00 → 02:00, so 02:30 happens twice.
      const saturday = local(2026, 10, 24, 2, 30);
      const move = moveToDay(saturday, day(2026, 10, 25), new Date(2026, 9, 1));
      expect(move.kind).toBe("valid");
      const moved = new Date(move.at);
      expect(Number.isNaN(moved.getTime())).toBe(false);
      expect([moved.getDate(), moved.getHours(), moved.getMinutes()]).toEqual([
        25, 2, 30,
      ]);
    });
  });
});
