import TikTokInboxDelivery from "../../components/TikTokInboxDelivery.tsx";
import type { Publication } from "../../types.ts";
import Button, { type ButtonVariant } from "../../ui/Button.tsx";
import StatusBadge from "../../ui/StatusBadge.tsx";
import {
  actionLabel,
  type ActionPlan,
  type PostAction,
} from "./post-actions.ts";

interface ActionButtonProps {
  action: PostAction;
  post: Publication;
  variant: ButtonVariant;
  busy?: boolean;
  onAction: (action: PostAction) => void;
}

/** One action of the panel: a link where it leaves, a button otherwise. */
export function ActionButton({
  action,
  post,
  variant,
  busy = false,
  onAction,
}: ActionButtonProps) {
  const label = actionLabel(action, post);
  if (action === "open_settings") {
    return (
      <Button as="link" to="/settings" variant={variant}>
        {label}
      </Button>
    );
  }
  if (action === "open_on_platform" && post.latest_attempt?.external_url) {
    return (
      <a
        className={`ap-button ap-button--${variant}`}
        href={post.latest_attempt.external_url}
        target="_blank"
        rel="noreferrer noopener"
      >
        <span>{label}</span>
      </a>
    );
  }
  return (
    <Button variant={variant} loading={busy} onClick={() => onAction(action)}>
      {label}
    </Button>
  );
}

interface StatusActionPanelProps {
  post: Publication;
  plan: ActionPlan;
  onAction: (action: PostAction) => void;
  busy: PostAction | null;
  /** On phones the primary action sits in the sticky bar instead. */
  primaryElsewhere: boolean;
  onPostChanged: (post: Publication) => void;
}

/**
 * Always visible: the state, one sentence about it, one primary action and at
 * most one secondary (a Failed Post also offers Move to drafts).
 */
function StatusActionPanel({
  post,
  plan,
  onAction,
  busy,
  primaryElsewhere,
  onPostChanged,
}: StatusActionPanelProps) {
  const inbox =
    post.display_state === "needs_action" && post.account.platform === "tiktok";
  return (
    <section className="ap-status-panel" aria-label="Status">
      <StatusBadge post={post.display_state} />
      <p className="ap-status-panel__sentence">{plan.sentence}</p>
      {inbox ? (
        // Check status lives with the delivery it checks (one request, never polled).
        <TikTokInboxDelivery publication={post} onChanged={onPostChanged} />
      ) : (
        <div className="ap-status-panel__actions">
          {plan.primary && !primaryElsewhere && (
            <ActionButton
              action={plan.primary}
              post={post}
              variant="primary"
              busy={busy === plan.primary}
              onAction={onAction}
            />
          )}
          {plan.secondary && (
            <ActionButton
              action={plan.secondary}
              post={post}
              variant="secondary"
              busy={busy === plan.secondary}
              onAction={onAction}
            />
          )}
          {plan.tertiary && (
            <ActionButton
              action={plan.tertiary}
              post={post}
              variant="ghost"
              busy={busy === plan.tertiary}
              onAction={onAction}
            />
          )}
        </div>
      )}
    </section>
  );
}

export default StatusActionPanel;
