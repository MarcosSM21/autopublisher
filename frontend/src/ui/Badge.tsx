import type { ReactNode } from "react";
import Icon, { type IconName } from "./Icon.tsx";

export type Tone = "neutral" | "active" | "success" | "warning" | "danger";

interface BadgeProps {
  tone?: Tone;
  icon?: IconName;
  children: ReactNode;
}

/** Short label; colour only reinforces the text, never replaces it. */
function Badge({ tone = "neutral", icon, children }: BadgeProps) {
  return (
    <span className={`ap-badge ap-badge--${tone}`}>
      {icon && <Icon name={icon} size={14} />}
      <span>{children}</span>
    </span>
  );
}

export default Badge;
