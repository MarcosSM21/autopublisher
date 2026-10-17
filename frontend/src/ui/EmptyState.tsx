import type { ReactElement } from "react";
import { Link } from "react-router";

interface EmptyStateProps {
  title: string;
  description?: string;
  /** Exactly one primary action (required by type), e.g. a primary Button. */
  action: ReactElement;
  /** Optional secondary path, always a plain link. */
  secondary?: { to: string; label: string };
  headingLevel?: 2 | 3;
}

/** What is missing and the single next step. */
function EmptyState({
  title,
  description,
  action,
  secondary,
  headingLevel = 2,
}: EmptyStateProps) {
  const Heading = headingLevel === 2 ? "h2" : "h3";
  return (
    <div className="ap-empty">
      <Heading className="ap-empty__title">{title}</Heading>
      {description && <p className="ap-empty__text">{description}</p>}
      <div className="ap-empty__actions">
        {action}
        {secondary && (
          <Link className="ap-link" to={secondary.to}>
            {secondary.label}
          </Link>
        )}
      </div>
    </div>
  );
}

export default EmptyState;
