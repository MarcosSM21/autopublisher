import type { Publication } from "../../types.ts";
import {
  attemptPercent,
  attemptPhaseLabel,
  formatDate,
  isPlatformStage,
} from "../../utils.ts";
import { timeZoneLabel } from "./calendar.ts";

const MODES: Partial<Record<Publication["display_state"], string>> = {
  scheduled_automatic: "AutoPublisher publishes it automatically.",
  scheduled_paused:
    "Automatic, but automation is paused: it waits until you resume it.",
  scheduled_manual: "Needs you to publish it (no automatic publishing).",
  missed: "Its time passed without publishing.",
};

/** When the Post goes (or went) out, in the browser's time zone. */
function PostWhen({ post }: { post: Publication }) {
  const attempt = post.latest_attempt;
  let main: string;
  if (post.display_state === "publishing" && attempt) {
    main = isPlatformStage(attempt)
      ? `${attemptPhaseLabel(attempt)}…`
      : `${attemptPhaseLabel(attempt)} · ${attemptPercent(attempt)}%`;
  } else if (post.display_state === "published" && post.published_at) {
    main = `Published ${formatDate(post.published_at)}`;
  } else if (post.scheduled_at) {
    main = `Scheduled for ${formatDate(post.scheduled_at)}`;
  } else {
    main = "Not scheduled";
  }
  const mode = MODES[post.display_state];
  return (
    <section className="ap-post-detail__section" aria-labelledby="post-when">
      <h3 id="post-when" className="ap-post-detail__title">
        When
      </h3>
      <p>{main}</p>
      {mode && <p className="ap-meta">{mode}</p>}
      {(post.scheduled_at || post.published_at) && (
        <p className="ap-meta">Time zone: {timeZoneLabel()}</p>
      )}
      {post.auto_publish_error && (
        <p className="ap-field__error">
          Couldn't start automatically: {post.auto_publish_error.message}
        </p>
      )}
    </section>
  );
}

export default PostWhen;
