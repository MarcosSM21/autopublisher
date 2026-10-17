import type { HTMLAttributes, ReactNode } from "react";

type CardProps = HTMLAttributes<HTMLElement> & {
  /** `section` when the card has its own heading; `div` otherwise. */
  as?: "div" | "section" | "article" | "li";
  children: ReactNode;
};

/** A bordered surface without shadow. */
function Card({
  as: Element = "div",
  className,
  children,
  ...rest
}: CardProps) {
  return (
    <Element
      className={className ? `ap-card ${className}` : "ap-card"}
      {...rest}
    >
      {children}
    </Element>
  );
}

export default Card;
