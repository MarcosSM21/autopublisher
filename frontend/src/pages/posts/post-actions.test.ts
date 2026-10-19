import { expect, it } from "vitest";
import type { PostDisplayState } from "../../types.ts";
import { postActions, rowHint, type PostAction } from "./post-actions.ts";
import type { Readiness } from "./readiness.ts";
import { attempt, post } from "./test-posts.ts";

const future = "2099-01-01T10:00:00Z";
const problem: Readiness = { state: "needs_details", summary: "Privacy" };

it.each<
  [
    string,
    ReturnType<typeof post>,
    Readiness | null,
    boolean,
    [PostAction | null, PostAction | null, PostAction | null],
  ]
>([
  [
    "draft with media",
    post("draft"),
    null,
    false,
    ["continue_publish", null, null],
  ],
  [
    "text draft",
    post("draft", { content_id: null }),
    null,
    false,
    ["continue_setup", null, null],
  ],
  [
    "scheduled automatic",
    post("scheduled_automatic", { scheduled_at: future }),
    { state: "ready" },
    false,
    ["edit_schedule", "publish_now", null],
  ],
  [
    "scheduled with details missing",
    post("scheduled_automatic", { scheduled_at: future }),
    problem,
    false,
    ["complete_details", "edit_schedule", null],
  ],
  [
    "paused",
    post("scheduled_paused", { scheduled_at: future }),
    null,
    true,
    ["edit_schedule", "open_settings", null],
  ],
  [
    "paused and incomplete: the Post's need wins",
    post("scheduled_paused", { scheduled_at: future }),
    problem,
    true,
    ["complete_details", "edit_schedule", null],
  ],
  [
    "legacy manual",
    post("scheduled_manual", { scheduled_at: future }),
    null,
    false,
    ["publish_automatically", "publish_now", null],
  ],
  [
    "missed",
    post("missed", { scheduled_at: "2020-01-01T10:00:00Z" }),
    null,
    false,
    ["reschedule", "publish_now", null],
  ],
  [
    "failed",
    post("failed"),
    null,
    false,
    ["retry_now", "reschedule", "move_to_drafts"],
  ],
  [
    "needs review: only Check result",
    post("needs_review"),
    null,
    false,
    ["check_result", null, null],
  ],
  [
    "needs action",
    post("needs_action"),
    null,
    false,
    ["check_status", null, null],
  ],
  ["publishing", post("publishing"), null, false, [null, null, null]],
  [
    "published with a link",
    post("published", {
      latest_attempt: attempt({ external_url: "https://x" }),
    }),
    null,
    false,
    ["open_on_platform", null, null],
  ],
  ["cancelled", post("cancelled"), null, false, ["reactivate", null, null]],
])("%s", (_, candidate, readiness, paused, [primary, secondary, tertiary]) => {
  const plan = postActions(candidate, readiness, paused);
  expect([plan.primary, plan.secondary, plan.tertiary]).toEqual([
    primary,
    secondary,
    tertiary,
  ]);
  expect(plan.sentence.length).toBeGreaterThan(0);
});

it("paused and incomplete still says automation is paused", () => {
  expect(
    postActions(
      post("scheduled_paused", { scheduled_at: future }),
      problem,
      true,
    ).sentence,
  ).toMatch(/Automation is paused/);
});

it("a summary that ends a sentence is not followed by a second period", () => {
  const sentence = postActions(
    post("scheduled_automatic", { scheduled_at: future }),
    { state: "blocked", summary: "Telegram is not configured." },
    false,
  ).sentence;
  expect(sentence).toMatch(/: Telegram is not configured\.$/);
});

it.each<[PostDisplayState, Readiness | null, string, string | null]>([
  ["failed", null, "youtube", "Retry or reschedule"],
  ["needs_review", null, "youtube", "Check result"],
  ["needs_action", null, "tiktok", "Finish in TikTok"],
  ["missed", null, "youtube", "Reschedule or publish now"],
  [
    "scheduled_automatic",
    { state: "needs_details", summary: "Privacy" },
    "youtube",
    "Add details · Privacy",
  ],
  [
    "scheduled_automatic",
    { state: "needs_details", summary: "Couldn't verify requirements" },
    "youtube",
    "Check requirements",
  ],
  [
    "scheduled_automatic",
    { state: "blocked", summary: "Reconnect account" },
    "youtube",
    "Reconnect account",
  ],
  ["scheduled_automatic", { state: "ready" }, "youtube", null],
])("hint of %s", (state, readiness, platform, hint) => {
  const candidate = post(state, {
    account: {
      id: 5,
      platform: platform as never,
      handle: "a",
      display_name: null,
      is_active: true,
    },
  });
  expect(rowHint(candidate, readiness)).toBe(hint);
});
