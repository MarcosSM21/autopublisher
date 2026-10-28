import type { AnimationEvent, ReactNode } from "react";
import Icon, { type IconName } from "./Icon.tsx";

export type Tone = "neutral" | "active" | "success" | "warning" | "danger";

interface BadgeProps {
  tone?: Tone;
  icon?: IconName;
  /** A decorative dot while the work is in progress (Publishing). */
  activity?: boolean;
  /** A one-time emphasis (just Published); cleared by `onEmphasisEnd`. */
  emphasis?: boolean;
  onEmphasisEnd?: () => void;
  children: ReactNode;
}

/** Short label; colour only reinforces the text, never replaces it. */
function Badge({
  tone = "neutral",
  icon,
  activity = false,
  emphasis = false,
  onEmphasisEnd,
  children,
}: BadgeProps) {
  // Only the emphasis' own end: the dot's pulse bubbles here too.
  function handleAnimationEnd(event: AnimationEvent<HTMLSpanElement>) {
    if (event.animationName === "ap-badge-emphasis") {
      onEmphasisEnd?.();
    }
  }

  return (
    <span
      className={`ap-badge ap-badge--${tone}`}
      data-activity={activity || undefined}
      data-emphasis={emphasis || undefined}
      onAnimationEnd={onEmphasisEnd ? handleAnimationEnd : undefined}
    >
      {icon && <Icon name={icon} size={14} />}
      {activity && <span className="ap-badge__activity" aria-hidden="true" />}
      <span>{children}</span>
    </span>
  );
}

export default Badge;
