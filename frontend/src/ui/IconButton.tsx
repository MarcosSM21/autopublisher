import type { ButtonHTMLAttributes } from "react";
import Icon, { type IconName } from "./Icon.tsx";

type IconButtonProps = Omit<
  ButtonHTMLAttributes<HTMLButtonElement>,
  "children" | "aria-label"
> & {
  icon: IconName;
  /** Required: the only accessible name of an icon-only button. */
  label: string;
  /**
   * Optional tooltip, only for information the label does not already give.
   * Never set it to the label: understanding the action must not need a tooltip.
   */
  title?: string;
};

/** Icon-only button, 44×44 px; its label is announced, the icon is hidden. */
function IconButton({
  icon,
  label,
  className,
  type = "button",
  ...rest
}: IconButtonProps) {
  return (
    <button
      type={type}
      className={className ? `ap-icon-button ${className}` : "ap-icon-button"}
      aria-label={label}
      {...rest}
    >
      <Icon name={icon} />
    </button>
  );
}

export default IconButton;
