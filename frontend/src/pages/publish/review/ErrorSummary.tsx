import { useEffect, useRef, type MouseEvent } from "react";
import type { SummaryItem } from "../final-action.ts";
import { focusTarget } from "../focus.ts";

interface ErrorSummaryProps {
  items: SummaryItem[];
  title?: string;
}

/**
 * What must be fixed before anything starts: an alert that takes the focus,
 * with one link per problem that moves the focus to it. The inline errors stay
 * next to their fields.
 */
function ErrorSummary({
  items,
  title = "Fix these before continuing",
}: ErrorSummaryProps) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (items.length > 0) {
      ref.current?.focus();
    }
  }, [items]);
  if (items.length === 0) {
    return null;
  }
  const follow = (target: string) => (event: MouseEvent) => {
    event.preventDefault();
    focusTarget(target);
  };
  return (
    <div
      ref={ref}
      className="ap-error-summary"
      role="alert"
      tabIndex={-1}
      aria-labelledby="publish-error-summary-title"
    >
      <h2 id="publish-error-summary-title" className="ap-error-summary__title">
        {title}
      </h2>
      <ul className="ap-error-summary__list">
        {items.map((item) => (
          <li key={`${item.target}:${item.text}`}>
            <a
              className="ap-link"
              href={`#${item.target}`}
              onClick={follow(item.target)}
            >
              {item.text}
            </a>
          </li>
        ))}
      </ul>
    </div>
  );
}

export default ErrorSummary;
