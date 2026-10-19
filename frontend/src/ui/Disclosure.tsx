import {
  useId,
  useRef,
  useState,
  type KeyboardEvent,
  type ReactNode,
} from "react";

interface DisclosureProps {
  /** Visible text of the toggle button. */
  label: ReactNode;
  children: ReactNode;
  className?: string;
  /** Initial state when uncontrolled. */
  defaultOpen?: boolean;
  /** Controlled state (e.g. a card that opens when something is missing). */
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
}

/**
 * A button that shows or hides a region (not an ARIA menu). Escape closes it and
 * returns focus to the button. Opens on click/tap only, never on hover.
 */
function Disclosure({
  label,
  children,
  className,
  defaultOpen = false,
  open: controlledOpen,
  onOpenChange,
}: DisclosureProps) {
  const [uncontrolledOpen, setUncontrolledOpen] = useState(defaultOpen);
  const open = controlledOpen ?? uncontrolledOpen;
  const regionId = useId();
  const buttonRef = useRef<HTMLButtonElement>(null);

  function setOpen(value: boolean) {
    setUncontrolledOpen(value);
    onOpenChange?.(value);
  }

  function handleKeyDown(event: KeyboardEvent) {
    if (event.key === "Escape" && open) {
      event.stopPropagation();
      setOpen(false);
      buttonRef.current?.focus();
    }
  }

  return (
    <div
      className={className ? `ap-disclosure ${className}` : "ap-disclosure"}
      onKeyDown={handleKeyDown}
    >
      <button
        ref={buttonRef}
        type="button"
        className="ap-button ap-button--ghost"
        aria-expanded={open}
        aria-controls={regionId}
        onClick={() => setOpen(!open)}
      >
        {label}
      </button>
      <div id={regionId} className="ap-disclosure__region" hidden={!open}>
        {children}
      </div>
    </div>
  );
}

export default Disclosure;
