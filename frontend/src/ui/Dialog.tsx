// Modal surfaces on one accessible foundation (@radix-ui/react-dialog): focus is
// trapped while open, Escape and the overlay close, focus returns to the element
// that opened it, the background is inert. Our CSS decides how each one looks.
import * as RadixDialog from "@radix-ui/react-dialog";
import { useRef, type ReactNode } from "react";
import IconButton from "./IconButton.tsx";

type Variant = "dialog" | "drawer" | "sheet";

interface ModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Required: the accessible name of the surface, shown as its heading. */
  title: string;
  description?: string;
  children: ReactNode;
  /** Actions shown at the bottom (one primary at most). */
  footer?: ReactNode;
}

function Modal({
  variant,
  open,
  onOpenChange,
  title,
  description,
  children,
  footer,
}: ModalProps & { variant: Variant }) {
  // Radix returns focus only to its own Trigger; our surfaces open from links,
  // routes or state, so remember what had focus and give it back on close.
  const opener = useRef<HTMLElement | null>(null);
  return (
    <RadixDialog.Root open={open} onOpenChange={onOpenChange}>
      <RadixDialog.Portal>
        <RadixDialog.Overlay className="ap-overlay" />
        <RadixDialog.Content
          className={`ap-modal ap-modal--${variant}`}
          onOpenAutoFocus={() => {
            opener.current =
              document.activeElement instanceof HTMLElement
                ? document.activeElement
                : null;
          }}
          onCloseAutoFocus={(event) => {
            if (opener.current?.isConnected) {
              event.preventDefault();
              opener.current.focus();
            }
          }}
          // Without a description, say so explicitly instead of pointing nowhere.
          {...(description ? {} : { "aria-describedby": undefined })}
        >
          <header className="ap-modal__header">
            <RadixDialog.Title className="ap-modal__title">
              {title}
            </RadixDialog.Title>
            <RadixDialog.Close asChild>
              <IconButton icon="close" label="Close" />
            </RadixDialog.Close>
          </header>
          {description && (
            <RadixDialog.Description className="ap-modal__description">
              {description}
            </RadixDialog.Description>
          )}
          <div className="ap-modal__body">{children}</div>
          {footer && <footer className="ap-modal__footer">{footer}</footer>}
        </RadixDialog.Content>
      </RadixDialog.Portal>
    </RadixDialog.Root>
  );
}

/** Centred dialog for a short decision. */
export function Dialog(props: ModalProps) {
  return <Modal variant="dialog" {...props} />;
}

/** Panel anchored to the right edge (tablet and desktop details). */
export function Drawer(props: ModalProps) {
  return <Modal variant="drawer" {...props} />;
}

/** Full screen on phones, centred from md up (e.g. Add account). */
export function Sheet(props: ModalProps) {
  return <Modal variant="sheet" {...props} />;
}
