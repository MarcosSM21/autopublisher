// What each Post of the set looks like in Results (spec FR-053/FR-054), and
// the aggregate line by outcome. From the backend's display state and the
// last action's step only.
import type { Tone } from "../../ui/Badge.tsx";
import type { IconName } from "../../ui/Icon.tsx";
import { POST_STATUS } from "../../ui/status.ts";
import type { Publication } from "../../types.ts";
import { attemptPhaseLabel, formatWhen, isPlatformStage } from "../../utils.ts";
import type { PostStep } from "./usePublishTask.ts";
import { problemText } from "../../components/platform/problem-copy.ts";

function attemptError(post: Publication): string | null {
  const error = post.latest_attempt?.error;
  return error ? problemText(error.message, error.code) : null;
}

export type Outcome =
  | "published"
  | "publishing"
  | "scheduled"
  | "ready_in_tiktok"
  | "needs_action"
  | "failed"
  | "needs_review"
  | "missed"
  | "didnt_start"
  | "still_draft"
  | "cancelled";

export interface ResultView {
  outcome: Outcome;
  label: string;
  tone: Tone;
  icon: IconName;
  detail: string | null;
  /** Rows with a problem offer `Open post`. */
  problem: boolean;
}

export function resultView(
  post: Publication,
  step: PostStep | undefined,
): ResultView {
  const look = POST_STATUS[post.display_state];
  const base = {
    tone: look.tone,
    icon: look.icon,
    detail: null,
    problem: false,
  };
  switch (post.display_state) {
    case "draft":
      return step?.run === "schedule"
        ? {
            ...base,
            outcome: "still_draft",
            label: "Still a draft",
            tone: "warning",
            icon: "alert",
            detail: step.message,
            problem: true,
          }
        : {
            ...base,
            outcome: "didnt_start",
            label: "Didn't start",
            tone: "warning",
            icon: "alert",
            detail: step?.message ?? null,
            problem: true,
          };
    case "publishing": {
      const attempt = post.latest_attempt;
      const processing = attempt !== null && isPlatformStage(attempt);
      return {
        ...base,
        outcome: "publishing",
        label: processing ? "Processing" : "Publishing…",
        detail: attempt ? attemptPhaseLabel(attempt) : null,
      };
    }
    case "published":
      return { ...base, outcome: "published", label: "Published" };
    case "scheduled_automatic":
    case "scheduled_manual":
    case "scheduled_paused":
      return {
        ...base,
        outcome: "scheduled",
        label: look.label,
        detail: post.scheduled_at ? formatWhen(post.scheduled_at) : null,
      };
    case "needs_action":
      return post.account.platform === "tiktok"
        ? {
            ...base,
            outcome: "ready_in_tiktok",
            label: "Ready in TikTok",
            detail: "Finish the post in the TikTok app.",
            problem: true,
          }
        : {
            ...base,
            outcome: "needs_action",
            label: look.label,
            problem: true,
          };
    case "failed":
      return {
        ...base,
        outcome: "failed",
        label: "Failed",
        detail: attemptError(post),
        problem: true,
      };
    case "needs_review":
      return {
        ...base,
        outcome: "needs_review",
        label: "Needs review",
        detail: "Check whether it was published before trying again.",
        problem: true,
      };
    case "missed":
      return { ...base, outcome: "missed", label: "Missed", problem: true };
    case "cancelled":
      return { ...base, outcome: "cancelled", label: "Cancelled" };
  }
}

const ORDER: Outcome[] = [
  "published",
  "publishing",
  "scheduled",
  "ready_in_tiktok",
  "needs_action",
  "failed",
  "needs_review",
  "missed",
  "didnt_start",
  "still_draft",
  "cancelled",
];

function phrase(outcome: Outcome, count: number): string {
  const plural = count !== 1;
  switch (outcome) {
    case "published":
      return `${count} published`;
    case "publishing":
      return `${count} publishing`;
    case "scheduled":
      return `${count} scheduled`;
    case "ready_in_tiktok":
      return `${count} ready in TikTok`;
    case "needs_action":
      return `${count} ${plural ? "need" : "needs"} action`;
    case "failed":
      return `${count} failed`;
    case "needs_review":
      return `${count} ${plural ? "need" : "needs"} review`;
    case "missed":
      return `${count} missed`;
    case "didnt_start":
      return `${count} didn't start`;
    case "still_draft":
      return `${count} still ${plural ? "drafts" : "a draft"}`;
    case "cancelled":
      return `${count} cancelled`;
  }
}

/** e.g. "2 published · 1 failed"; never "Publish failed" for a partial result. */
export function aggregateLine(views: readonly ResultView[]): string {
  const counts = new Map<Outcome, number>();
  for (const view of views) {
    counts.set(view.outcome, (counts.get(view.outcome) ?? 0) + 1);
  }
  return ORDER.filter((outcome) => counts.has(outcome))
    .map((outcome) => phrase(outcome, counts.get(outcome)!))
    .join(" · ");
}
