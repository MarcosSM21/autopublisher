// Readiness of scheduled Posts (research R-06, plan §13): from the overview the
// project already loaded and the account health, never from a new check. Within
// 7 days a scheduled Post is Needs details, Blocked or Ready; beyond, nothing is
// promised.
import type { AccountHealth, Overview, Publication } from "../../types.ts";
import { problemText } from "../../components/platform/problem-copy.ts";

export const READINESS_HORIZON_MS = 7 * 24 * 60 * 60 * 1000;
export const COULD_NOT_VERIFY = "Couldn't verify requirements";

export type Readiness =
  | { state: "needs_details"; summary: string }
  | { state: "blocked"; summary: string }
  | { state: "ready" };

export interface ReadinessSource {
  /** Post id → the overview's "incomplete" detail. */
  incomplete: ReadonlyMap<number, string>;
  /** Accounts that are active but not ready, with their reason. */
  blocked: ReadonlyMap<number, string>;
  now: Date;
}

const BLOCKED_REASONS: Partial<Record<AccountHealth["state"], string>> = {
  reconnect_needed: "Reconnect account",
  not_connected: "Connect account",
  setup_required: "Finish account setup",
};

export function readinessSource(
  overview: Overview | null,
  health: readonly AccountHealth[],
  now: Date = new Date(),
): ReadinessSource {
  const incomplete = new Map<number, string>();
  for (const item of overview?.attention ?? []) {
    if (item.kind === "incomplete" && item.post) {
      incomplete.set(
        item.post.id,
        item.detail ? problemText(item.detail) : COULD_NOT_VERIFY,
      );
    }
  }
  const blocked = new Map<number, string>();
  for (const account of health) {
    if (!account.is_active) {
      continue;
    }
    const reason = BLOCKED_REASONS[account.state];
    if (reason) {
      blocked.set(
        account.account_id,
        account.state === "setup_required" &&
          account.issue?.code === "channel_required"
          ? "Choose a channel"
          : reason,
      );
    }
  }
  return { incomplete, blocked, now };
}

/** Null outside the horizon, or for a Post that isn't scheduled. */
export function readinessOf(
  post: Pick<
    Publication,
    "id" | "account_id" | "display_state" | "scheduled_at"
  >,
  source: ReadinessSource,
): Readiness | null {
  if (!post.display_state.startsWith("scheduled_") || !post.scheduled_at) {
    return null;
  }
  const at = new Date(post.scheduled_at).getTime();
  const now = source.now.getTime();
  if (at <= now || at > now + READINESS_HORIZON_MS) {
    return null;
  }
  const detail = source.incomplete.get(post.id);
  if (detail !== undefined) {
    return { state: "needs_details", summary: detail };
  }
  const blocked = source.blocked.get(post.account_id);
  if (blocked !== undefined) {
    return { state: "blocked", summary: blocked };
  }
  return { state: "ready" };
}

export function hasProblem(readiness: Readiness | null): boolean {
  return readiness !== null && readiness.state !== "ready";
}
