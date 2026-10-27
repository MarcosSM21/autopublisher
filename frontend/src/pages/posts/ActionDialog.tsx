import { useEffect, useRef, useState, type ReactNode } from "react";
import { Link } from "react-router";
import {
  getPublishCheck,
  publishNow,
  updatePublication,
  type PublicationUpdate,
} from "../../api.ts";
import TikTokDeclaration from "../../components/platform/TikTokDeclaration.tsx";
import type { Publication, PublishCheck } from "../../types.ts";
import { MEDIA_MD_UP } from "../../ui/breakpoints.ts";
import Button from "../../ui/Button.tsx";
import { Dialog, Sheet } from "../../ui/Dialog.tsx";
import Field from "../../ui/Field.tsx";
import { useMediaQuery } from "../../ui/useMediaQuery.ts";
import {
  accountName,
  fromDateTimeLocalValue,
  isFuture,
  toApiError,
  toDateTimeLocalValue,
} from "../../utils.ts";
import { useActionDeclaration } from "./useActionDeclaration.ts";
import { problemText } from "../../components/platform/problem-copy.ts";

export type DialogAction =
  | "publish_now"
  | "retry_now"
  | "reschedule"
  | "edit_schedule"
  | "publish_automatically"
  | "move_to_drafts";

const TITLES: Record<DialogAction, string> = {
  publish_now: "Publish now",
  retry_now: "Retry now",
  reschedule: "Reschedule",
  edit_schedule: "Edit schedule",
  publish_automatically: "Publish automatically",
  move_to_drafts: "Move to drafts",
};

const NEEDS_DATE: DialogAction[] = ["reschedule", "edit_schedule"];
const STARTS: DialogAction[] = ["publish_now", "retry_now"];
/** Actions that publish or arm: a TikTok Direct Post needs the declaration. */
const NEEDS_DECLARATION: DialogAction[] = [
  "publish_now",
  "retry_now",
  "reschedule",
  "edit_schedule",
  "publish_automatically",
];

interface ActionDialogProps {
  action: DialogAction;
  post: Publication;
  /** Every Post of the project (to find the one to check on a guard). */
  posts: readonly Publication[];
  paused: boolean;
  onClose: () => void;
  /** Awaited before the dialog stops being busy (e.g. to reload a list). */
  onDone: (post: Publication) => void | Promise<void>;
  /** Initial date and time (ISO instant), instead of the default one. */
  initialAt?: string;
  /** Called after an error is shown (e.g. to reload a list). */
  onFailed?: () => void;
  /** Where focus goes on close (see `Modal`); the opener by default. */
  returnFocus?: () => HTMLElement | null;
}

function timeZone(): string {
  return Intl.DateTimeFormat().resolvedOptions().timeZone;
}

/**
 * The confirmation of one Post detail action: what will happen, the date when
 * it schedules (always automatic, R4), the TikTok declaration when it publishes
 * or arms a Direct Post, then the existing endpoint. A Dialog from md, a Sheet
 * on phones.
 */
function ActionDialog({
  action,
  post,
  posts,
  paused,
  onClose,
  onDone,
  initialAt,
  onFailed,
  returnFocus,
}: ActionDialogProps) {
  const isMedium = useMediaQuery(MEDIA_MD_UP);
  const Surface = isMedium ? Dialog : Sheet;
  const needsDate = NEEDS_DATE.includes(action);
  const declaration = useActionDeclaration(
    post,
    NEEDS_DECLARATION.includes(action),
  );
  const [at, setAt] = useState(
    initialAt !== undefined
      ? toDateTimeLocalValue(initialAt)
      : action === "edit_schedule" && isFuture(post.scheduled_at)
        ? toDateTimeLocalValue(post.scheduled_at!)
        : "",
  );
  const [dateError, setDateError] = useState<string | null>(null);
  const [error, setError] = useState<ReactNode>(null);
  const [check, setCheck] = useState<PublishCheck | null>(null);
  const [busy, setBusy] = useState(false);
  // A ref, not only state: a double click never sends two requests.
  const sending = useRef(false);
  const name = accountName(post.account);

  useEffect(() => {
    if (!STARTS.includes(action)) {
      return;
    }
    let active = true;
    getPublishCheck(post.id)
      .then((loaded) => active && setCheck(loaded))
      .catch(() => {});
    return () => {
      active = false;
    };
  }, [action, post.id]);

  /** The guard of an uncertain result, never bypassed (FR-073a). */
  function guardMessage(): ReactNode {
    const related = posts.find(
      (other) =>
        other.display_state === "needs_review" &&
        other.account_id === post.account_id &&
        other.content_id === post.content_id &&
        other.content_id !== null,
    );
    return (
      <>
        Check the result first.{" "}
        {related ? (
          <Link
            className="ap-link"
            to={`/p/${post.project_id}/posts/${related.id}`}
          >
            Check result
          </Link>
        ) : (
          <Link className="ap-link" to={`/p/${post.project_id}/posts`}>
            Find it in Needs you
          </Link>
        )}
      </>
    );
  }

  async function run() {
    if (sending.current) {
      return;
    }
    if (needsDate) {
      if (!at) {
        setDateError("Choose a date and time.");
        return;
      }
      if (!isFuture(fromDateTimeLocalValue(at))) {
        setDateError("Choose a date and time in the future.");
        return;
      }
    }
    setDateError(null);
    if (!declaration.ready) {
      setError("Confirm the TikTok declaration first.");
      return;
    }
    sending.current = true;
    setBusy(true);
    setError(null);
    try {
      await declaration.record();
      let result: Publication;
      if (STARTS.includes(action)) {
        result = await publishNow(post.id, false);
      } else {
        const changes: PublicationUpdate =
          action === "move_to_drafts"
            ? { scheduled_at: null }
            : action === "publish_automatically"
              ? { auto_publish_enabled: true }
              : {
                  scheduled_at: fromDateTimeLocalValue(at),
                  auto_publish_enabled: true,
                };
        result = await updatePublication(post.id, changes);
      }
      await onDone(result);
    } catch (caught) {
      const apiError = toApiError(caught);
      if (apiError.code === "check_result_first") {
        setError(guardMessage());
      } else if (apiError.code === "tiktok_consent_stale") {
        declaration.control.onChange(null);
        setError("The TikTok details changed. Confirm the declaration again.");
      } else {
        setError(problemText(apiError.message, apiError.code));
      }
      sending.current = false;
      setBusy(false);
      onFailed?.();
    }
  }

  const readable =
    at && !Number.isNaN(new Date(at).getTime())
      ? new Date(at).toLocaleString(undefined, {
          dateStyle: "full",
          timeStyle: "short",
        })
      : null;

  return (
    <Surface
      open
      onOpenChange={(open) => !open && onClose()}
      title={TITLES[action]}
      returnFocus={returnFocus}
      footer={
        <>
          <Button variant="primary" loading={busy} onClick={() => void run()}>
            {declaration.inbox && STARTS.includes(action)
              ? "Send to TikTok"
              : TITLES[action]}
          </Button>
          <Button onClick={onClose}>Cancel</Button>
        </>
      }
    >
      <div className="ap-action-dialog">
        <p>
          {action === "move_to_drafts"
            ? `${name} goes back to Drafts, without a date. Its history is kept.`
            : action === "publish_automatically"
              ? `AutoPublisher will publish ${name} automatically at its scheduled time.`
              : STARTS.includes(action)
                ? `${name} starts publishing now.`
                : `${name} will be published automatically at the new time.`}
        </p>
        {check && check.summary.length > 0 && (
          <dl className="ap-action-dialog__summary">
            {check.summary.map((item) => (
              <div key={item.label}>
                <dt>{item.label}</dt>
                <dd>{item.value}</dd>
              </div>
            ))}
          </dl>
        )}
        {check && !check.eligible && (
          <ul className="ap-field__error" aria-label="Problems">
            {check.problems.map((problem) => (
              <li key={`${problem.code}-${problem.field ?? ""}`}>
                {problem.message}
              </li>
            ))}
          </ul>
        )}
        {needsDate && (
          <>
            <Field
              label="Date and time"
              hint={`Time zone: ${timeZone()}`}
              error={dateError}
              required
            >
              {(control) => (
                <input
                  {...control}
                  type="datetime-local"
                  value={at}
                  onChange={(event) => setAt(event.target.value)}
                />
              )}
            </Field>
            {readable && <p className="ap-when__preview">{readable}</p>}
            <p className="ap-meta">
              AutoPublisher will publish this post automatically at this time.
            </p>
          </>
        )}
        {paused && action !== "move_to_drafts" && !STARTS.includes(action) && (
          <p className="ap-notice">
            Automation is paused: it won't be published until you resume it.{" "}
            <Link className="ap-link" to="/settings">
              Open Settings
            </Link>
          </p>
        )}
        {declaration.inbox && STARTS.includes(action) && (
          <p>
            AutoPublisher will upload this video to TikTok. You'll get a TikTok
            inbox notification to finish the post.
          </p>
        )}
        {declaration.error && (
          <p className="ap-field__error">{declaration.error}</p>
        )}
        {declaration.required && declaration.options && (
          <TikTokDeclaration
            options={declaration.options}
            {...declaration.control}
          />
        )}
        {error && (
          <p className="ap-field__error" role="alert">
            {error}
          </p>
        )}
      </div>
    </Surface>
  );
}

export default ActionDialog;
