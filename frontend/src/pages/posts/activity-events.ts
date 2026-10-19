// The attempts of a Post as human events (spec FR-076): "Tue 18:00 · Started
// automatically", "Tue 18:01 · Failed: <message>". Codes stay out of them.
import { platformLabel, type PublicationAttempt } from "../../types.ts";
import { attemptPhaseLabel } from "../../utils.ts";
import { problemText } from "../../components/platform/problem-copy.ts";

/** e.g. "Tue 18:00". */
function moment(value: string): string {
  const date = new Date(value);
  return `${date.toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short" })} ${date.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })}`;
}

/** The human events of one attempt, oldest first. */
export function attemptEvents(attempt: PublicationAttempt): string[] {
  const platform = platformLabel(attempt.platform);
  const events = [
    `${moment(attempt.started_at)} · ${attempt.trigger === "scheduled" ? "Started automatically" : "Started manually"}`,
  ];
  const end = attempt.finished_at ? moment(attempt.finished_at) : null;
  if (attempt.status === "running") {
    events.push(`Now · ${attemptPhaseLabel(attempt)}`);
  } else if (attempt.status === "succeeded") {
    events.push(
      `${end} · ${attempt.details.delivered_to_inbox === true ? "Sent to your TikTok inbox" : `Published on ${platform}`}`,
    );
  } else if (attempt.requires_manual_review) {
    events.push(`${end} · Result uncertain: ${platform} may have published it`);
  } else {
    events.push(
      `${end} · Failed${attempt.error ? `: ${problemText(attempt.error.message, attempt.error.code)}` : ""}`,
    );
  }
  for (const warning of attempt.warnings) {
    events.push(`${end ?? moment(attempt.started_at)} · ${warning.message}`);
  }
  return events;
}
