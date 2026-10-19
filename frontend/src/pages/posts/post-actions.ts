// What a Post needs and what can be done now (spec FR-071, contracts/ui.md §5):
// one sentence, one primary action, at most one secondary (and, for Failed,
// a tertiary Move to drafts). From the display state and readiness only.
import { platformLabel, type Publication } from "../../types.ts";
import { formatWhen } from "../../utils.ts";
import { hasProblem, type Readiness } from "./readiness.ts";

export type PostAction =
  | "continue_publish"
  | "continue_setup"
  | "edit_schedule"
  | "publish_now"
  | "complete_details"
  | "open_settings"
  | "publish_automatically"
  | "reschedule"
  | "retry_now"
  | "move_to_drafts"
  | "check_result"
  | "check_status"
  | "open_on_platform"
  | "reactivate";

export interface ActionPlan {
  sentence: string;
  primary: PostAction | null;
  secondary: PostAction | null;
  tertiary: PostAction | null;
}

export const ACTION_LABELS: Record<PostAction, string> = {
  continue_publish: "Continue in Publish",
  continue_setup: "Continue setup",
  edit_schedule: "Edit schedule",
  publish_now: "Publish now",
  complete_details: "Complete details",
  open_settings: "Open Settings",
  publish_automatically: "Publish automatically",
  reschedule: "Reschedule",
  retry_now: "Retry now",
  move_to_drafts: "Move to drafts",
  check_result: "Check result",
  check_status: "Check status",
  open_on_platform: "Open on platform",
  reactivate: "Reactivate",
};

export function actionLabel(action: PostAction, post: Publication): string {
  return action === "open_on_platform"
    ? `Open on ${platformLabel(post.account.platform)}`
    : ACTION_LABELS[action];
}

function plan(
  sentence: string,
  primary: PostAction | null,
  secondary: PostAction | null = null,
  tertiary: PostAction | null = null,
): ActionPlan {
  return { sentence, primary, secondary, tertiary };
}

export function postActions(
  post: Publication,
  readiness: Readiness | null,
  paused: boolean,
): ActionPlan {
  const when = post.scheduled_at ? formatWhen(post.scheduled_at) : null;
  const platform = platformLabel(post.account.platform);
  if (post.display_state.startsWith("scheduled_") && hasProblem(readiness)) {
    const summary =
      readiness!.state === "ready"
        ? ""
        : readiness!.summary.replace(/[.!?]+$/, "");
    return plan(
      `This post needs attention before ${when}: ${summary}.${paused ? " Automation is paused, too." : ""}`,
      "complete_details",
      "edit_schedule",
    );
  }
  switch (post.display_state) {
    case "draft":
      return post.content_id === null
        ? plan(
            "This draft isn't scheduled yet. Continue setup to publish or schedule it.",
            "continue_setup",
          )
        : plan(
            "This draft isn't scheduled yet. Continue in Publish to publish or schedule it.",
            "continue_publish",
          );
    case "scheduled_automatic":
      return plan(
        `AutoPublisher will publish this automatically ${when}.`,
        "edit_schedule",
        "publish_now",
      );
    case "scheduled_paused":
      return plan(
        `Scheduled for ${when}, but automation is paused: it won't be published until you resume it.`,
        "edit_schedule",
        "open_settings",
      );
    case "scheduled_manual":
      return plan(
        `Scheduled for ${when}, but it needs you to publish it. Publish automatically to let AutoPublisher do it.`,
        "publish_automatically",
        "publish_now",
      );
    case "missed":
      return plan(
        `This post missed its time (${when}) and wasn't published.`,
        "reschedule",
        "publish_now",
      );
    case "failed":
      return plan(
        `Publishing failed${post.latest_attempt?.error ? `: ${post.latest_attempt.error.message}` : "."} Nothing was published.`,
        "retry_now",
        "reschedule",
        "move_to_drafts",
      );
    case "needs_review":
      return plan(
        `The last try to publish has an uncertain result: ${platform} may have published it. Check the result first.`,
        "check_result",
      );
    case "needs_action":
      return plan(
        post.account.platform === "tiktok"
          ? "The video is in your TikTok inbox. Finish the post in TikTok, then check its status."
          : `${platform} is waiting for you to finish this post.`,
        "check_status",
      );
    case "publishing":
      return plan(`Publishing to ${platform} now…`, null);
    case "published":
      return plan(
        `Published${post.published_at ? ` ${formatWhen(post.published_at)}` : ""}.`,
        post.latest_attempt?.external_url ? "open_on_platform" : null,
      );
    case "cancelled":
      return plan(
        "This post is cancelled. Reactivate it to use it again.",
        "reactivate",
      );
  }
}

/** The next-action hint of a row in Needs you (null elsewhere). */
export function rowHint(
  post: Publication,
  readiness: Readiness | null,
): string | null {
  switch (post.display_state) {
    case "failed":
      return "Retry or reschedule";
    case "needs_review":
      return "Check result";
    case "missed":
      return "Reschedule or publish now";
    case "needs_action":
      return post.account.platform === "tiktok"
        ? "Finish in TikTok"
        : "Finish on the platform";
  }
  if (readiness?.state === "needs_details") {
    return readiness.summary === "Couldn't verify requirements"
      ? "Check requirements"
      : `Add details · ${readiness.summary}`;
  }
  if (readiness?.state === "blocked") {
    return readiness.summary;
  }
  return null;
}
