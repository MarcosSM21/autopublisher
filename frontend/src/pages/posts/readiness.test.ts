import { expect, it } from "vitest";
import type { AccountHealth, Overview } from "../../types.ts";
import { readinessOf, readinessSource } from "./readiness.ts";
import { post } from "./test-posts.ts";

const NOW = new Date("2026-10-19T10:00:00Z");
const inDays = (days: number) =>
  new Date(NOW.getTime() + days * 86_400_000).toISOString();

const overview = {
  attention: [
    {
      kind: "incomplete",
      post: { id: 1 },
      detail: "Declare whether it's made for kids.",
    },
    {
      kind: "incomplete",
      post: { id: 2 },
      detail: "Couldn't verify requirements",
    },
    { kind: "failed", post: { id: 3 }, detail: "x" },
    {
      kind: "incomplete",
      post: { id: 50 },
      detail:
        "Telegram is not configured. Add your api_id and api_hash to the local Telegram app file (see docs/telegram.md).",
    },
  ],
} as unknown as Overview;

const health = [
  { account_id: 7, is_active: true, state: "reconnect_needed", issue: null },
  {
    account_id: 8,
    is_active: true,
    state: "setup_required",
    issue: { code: "channel_required", message: "" },
  },
  { account_id: 9, is_active: true, state: "ready", issue: null },
] as unknown as AccountHealth[];

const source = readinessSource(overview, health, NOW);

it.each([
  [
    "incomplete in the overview",
    post("scheduled_automatic", { id: 1, scheduled_at: inDays(2) }),
    { state: "needs_details", summary: "Declare whether it's made for kids." },
  ],
  [
    "a setup message from the backend, in human words",
    post("scheduled_automatic", { id: 50, scheduled_at: inDays(2) }),
    { state: "needs_details", summary: "Telegram connection needs setup." },
  ],
  [
    "couldn't verify",
    post("scheduled_paused", { id: 2, scheduled_at: inDays(1) }),
    { state: "needs_details", summary: "Couldn't verify requirements" },
  ],
  [
    "an account to reconnect",
    post("scheduled_automatic", {
      id: 4,
      account_id: 7,
      scheduled_at: inDays(3),
    }),
    { state: "blocked", summary: "Reconnect account" },
  ],
  [
    "a channel to choose",
    post("scheduled_manual", { id: 5, account_id: 8, scheduled_at: inDays(3) }),
    { state: "blocked", summary: "Choose a channel" },
  ],
  [
    "everything fine",
    post("scheduled_automatic", {
      id: 6,
      account_id: 9,
      scheduled_at: inDays(6),
    }),
    { state: "ready" },
  ],
  [
    "beyond 7 days",
    post("scheduled_automatic", { id: 1, scheduled_at: inDays(8) }),
    null,
  ],
  ["a Draft", post("draft", { id: 1 }), null],
  ["a Failed post", post("failed", { id: 3, scheduled_at: inDays(1) }), null],
])("%s", (_, candidate, expected) => {
  expect(readinessOf(candidate, source)).toEqual(expected);
});
