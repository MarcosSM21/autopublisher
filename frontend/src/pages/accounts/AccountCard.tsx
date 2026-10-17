import { useId } from "react";
import { Link } from "react-router";
import { platformLabel, type AccountHealth } from "../../types.ts";
import Button from "../../ui/Button.tsx";
import StatusBadge from "../../ui/StatusBadge.tsx";
import {
  capabilitiesText,
  identityText,
  primaryAction,
} from "./presentation.ts";

interface AccountCardProps {
  health: AccountHealth;
  /** Detail route of this account. */
  to: string;
  selected: boolean;
}

/** Platform + identity, state, the one action needed (or Details), capabilities. */
function AccountCard({ health, to, selected }: AccountCardProps) {
  const titleId = useId();
  const action = primaryAction(health);
  return (
    <li
      className={[
        "ap-account-card",
        health.is_active ? "" : "ap-account-card--inactive",
        selected ? "ap-account-card--selected" : "",
      ]
        .filter(Boolean)
        .join(" ")}
      aria-current={selected || undefined}
    >
      <div className="ap-account-card__main">
        <p id={titleId} className="ap-account-card__title">
          <strong>{platformLabel(health.platform)}</strong>{" "}
          <span>{identityText(health)}</span>
        </p>
        {health.display_name && (
          <p className="ap-meta ap-account-card__line">{health.display_name}</p>
        )}
        <StatusBadge account={health.state} />
        {health.issue && (
          <p className="ap-account-card__line">{health.issue.message}</p>
        )}
        {health.capabilities.length > 0 && (
          <p className="ap-meta ap-account-card__line">
            {capabilitiesText(health.capabilities)}
          </p>
        )}
      </div>
      <div className="ap-account-card__action">
        {action ? (
          <Button
            as="link"
            to={to}
            variant="secondary"
            aria-describedby={titleId}
          >
            {action}
          </Button>
        ) : (
          <Link className="ap-link" to={to} aria-describedby={titleId}>
            Details
          </Link>
        )}
      </div>
    </li>
  );
}

export default AccountCard;
