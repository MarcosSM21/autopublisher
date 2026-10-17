import type {
  AnchorHTMLAttributes,
  ButtonHTMLAttributes,
  ReactNode,
} from "react";
import { Link } from "react-router";
import Icon, { type IconName } from "./Icon.tsx";

export type ButtonVariant = "primary" | "secondary" | "ghost" | "danger";

interface CommonProps {
  /** At most one primary per view or empty state. */
  variant?: ButtonVariant;
  icon?: IconName;
  children: ReactNode;
  className?: string;
}

type ButtonProps = CommonProps &
  Omit<ButtonHTMLAttributes<HTMLButtonElement>, "className" | "children"> & {
    as?: "button";
    /** Disables the button and tells assistive technology it is working. */
    loading?: boolean;
  };

type LinkProps = CommonProps &
  Omit<
    AnchorHTMLAttributes<HTMLAnchorElement>,
    "className" | "children" | "href"
  > & {
    as: "link";
    to: string;
  };

function buttonClass(variant: ButtonVariant, extra?: string): string {
  return ["ap-button", `ap-button--${variant}`, extra]
    .filter(Boolean)
    .join(" ");
}

/** A button, or a link that looks like one (`as="link"`); always ≥ 44 px. */
function Button(props: ButtonProps | LinkProps) {
  if (props.as === "link") {
    const {
      as: _as,
      variant = "secondary",
      icon,
      children,
      className,
      to,
      ...rest
    } = props;
    return (
      <Link to={to} className={buttonClass(variant, className)} {...rest}>
        {icon && <Icon name={icon} />}
        <span>{children}</span>
      </Link>
    );
  }
  const {
    as: _as,
    variant = "secondary",
    icon,
    children,
    className,
    loading = false,
    disabled,
    type = "button",
    ...rest
  } = props;
  return (
    <button
      type={type}
      className={buttonClass(variant, className)}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      {...rest}
    >
      {loading ? (
        <span className="ap-spinner" aria-hidden="true" />
      ) : (
        icon && <Icon name={icon} />
      )}
      <span>{children}</span>
    </button>
  );
}

export default Button;
