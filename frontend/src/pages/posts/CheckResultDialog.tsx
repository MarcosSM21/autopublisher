import { useEffect, useRef, useState } from "react";
import { getPublication, getPublishCheck, publishNow } from "../../api.ts";
import TikTokDeclaration from "../../components/platform/TikTokDeclaration.tsx";
import { platformLabel, type Publication } from "../../types.ts";
import { MEDIA_MD_UP } from "../../ui/breakpoints.ts";
import Button from "../../ui/Button.tsx";
import { Dialog, Sheet } from "../../ui/Dialog.tsx";
import Skeleton from "../../ui/Skeleton.tsx";
import { POST_STATUS } from "../../ui/status.ts";
import { useMediaQuery } from "../../ui/useMediaQuery.ts";
import { formatDate, toApiError } from "../../utils.ts";
import { useActionDeclaration } from "./useActionDeclaration.ts";

interface CheckResultDialogProps {
  post: Publication;
  onClose: () => void;
  /** After the check (resolved) or a new attempt. */
  onDone: (post: Publication) => void;
}

function text(value: unknown): string | null {
  return typeof value === "string" && value !== "" ? value : null;
}

/** What helps to find the Post on the platform (never proof). */
function lookFor(post: Publication): { label: string; value: string }[] {
  const attempt = post.latest_attempt;
  const sent = attempt?.submitted ?? {};
  const where =
    text(sent.channel_title) ??
    (text(sent.username) ? `@${text(sent.username)}` : null) ??
    text(sent.creator_nickname);
  const what =
    text(sent.title) ??
    text(sent.caption) ??
    text(sent.text) ??
    post.description;
  return [
    ...(where ? [{ label: "Account", value: where }] : []),
    ...(what ? [{ label: "Content", value: what }] : []),
    ...(attempt
      ? [{ label: "Time", value: formatDate(attempt.started_at) }]
      : []),
  ];
}

type Phase =
  | { kind: "checking" }
  | { kind: "resolved"; post: Publication }
  | { kind: "uncertain"; post: Publication }
  | { kind: "error"; message: string };

/**
 * Check result of a Post whose last attempt is uncertain (spec FR-073a, C1):
 * first a read-only check that reconciles when the platform allows it. If the
 * result is known now, it says so. If it stays uncertain, the user can confirm
 * they checked the platform and it wasn't published; only then `Publish again`
 * starts a new attempt with `confirm_remote_checked`. Nothing else (no
 * Reschedule, no Move to drafts) is offered while it is uncertain.
 */
function CheckResultDialog({ post, onClose, onDone }: CheckResultDialogProps) {
  const isMedium = useMediaQuery(MEDIA_MD_UP);
  const Surface = isMedium ? Dialog : Sheet;
  const [phase, setPhase] = useState<Phase>({ kind: "checking" });
  const [acknowledged, setAcknowledged] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const sending = useRef(false);
  const declaration = useActionDeclaration(post, phase.kind === "uncertain");
  const platform = platformLabel(post.account.platform);

  useEffect(() => {
    let active = true;
    getPublishCheck(post.id)
      .then(() => getPublication(post.id))
      .then((fresh) => {
        if (active) {
          setPhase(
            fresh.display_state === "needs_review"
              ? { kind: "uncertain", post: fresh }
              : { kind: "resolved", post: fresh },
          );
        }
      })
      .catch(
        (caught: unknown) =>
          active &&
          setPhase({ kind: "error", message: toApiError(caught).message }),
      );
    return () => {
      active = false;
    };
  }, [post.id]);

  async function publishAgain() {
    if (sending.current || !acknowledged) {
      return;
    }
    if (!declaration.ready) {
      setError("Confirm the TikTok declaration first.");
      return;
    }
    sending.current = true;
    setBusy(true);
    setError(null);
    try {
      await declaration.record();
      onDone(await publishNow(post.id, true));
    } catch (caught) {
      setError(toApiError(caught).message);
      sending.current = false;
      setBusy(false);
    }
  }

  const close = () => {
    if (phase.kind === "resolved") {
      onDone(phase.post);
    } else {
      onClose();
    }
  };

  return (
    <Surface
      open
      onOpenChange={(open) => !open && close()}
      title="Check result"
      footer={
        phase.kind === "uncertain" ? (
          <>
            <Button
              variant="primary"
              disabled={!acknowledged}
              loading={busy}
              onClick={() => void publishAgain()}
            >
              Publish again
            </Button>
            <Button onClick={onClose}>Cancel</Button>
          </>
        ) : (
          <Button onClick={close}>Done</Button>
        )
      }
    >
      <div className="ap-action-dialog" aria-live="polite">
        {phase.kind === "checking" && (
          <Skeleton lines={2} label={`Checking with ${platform}…`} />
        )}
        {phase.kind === "error" && (
          <p className="ap-field__error" role="alert">
            {phase.message}
          </p>
        )}
        {phase.kind === "resolved" && (
          <p>
            The result is known now:{" "}
            {POST_STATUS[phase.post.display_state].label}.
          </p>
        )}
        {phase.kind === "uncertain" && (
          <>
            <p>
              {platform} may have published this post. Look for it on {platform}{" "}
              before publishing again:
            </p>
            <dl className="ap-action-dialog__summary">
              {lookFor(phase.post).map((item) => (
                <div key={item.label}>
                  <dt>{item.label}</dt>
                  <dd>{item.value}</dd>
                </div>
              ))}
            </dl>
            <label className="ap-check">
              <input
                type="checkbox"
                checked={acknowledged}
                onChange={(event) => setAcknowledged(event.target.checked)}
              />
              <span>I checked {platform} and this post was not published</span>
            </label>
            {declaration.required && declaration.options && (
              <TikTokDeclaration
                options={declaration.options}
                {...declaration.control}
              />
            )}
            {declaration.error && (
              <p className="ap-field__error">{declaration.error}</p>
            )}
          </>
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

export default CheckResultDialog;
