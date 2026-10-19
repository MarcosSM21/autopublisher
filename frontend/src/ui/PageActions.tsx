import type { ReactNode } from "react";

interface PageActionsProps {
  /** Accessible name of the action group, e.g. "Publish actions". */
  label: string;
  /** The page's primary action (at most one). */
  primary: ReactNode;
  /** At most one secondary action. */
  secondary?: ReactNode;
  /**
   * On phones, keep the actions in a bar stuck to the bottom of the viewport
   * while the page scrolls; on md+ they stay inline. CSS only: the DOM (and the
   * keyboard order) is the same at every width.
   */
  sticky?: boolean;
  className?: string;
}

/**
 * The actions of a page or task. A sticky bar also reserves scroll padding so
 * the focused element is never hidden behind it ("focus not obscured").
 */
function PageActions({
  label,
  primary,
  secondary,
  sticky = false,
  className,
}: PageActionsProps) {
  const classes = [
    "ap-page-actions",
    sticky ? "ap-page-actions--sticky" : null,
    className,
  ]
    .filter(Boolean)
    .join(" ");
  return (
    <div role="group" aria-label={label} className={classes}>
      {primary}
      {secondary}
    </div>
  );
}

export default PageActions;
