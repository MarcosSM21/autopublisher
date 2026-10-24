import { useState, type FormEvent } from "react";
import { changePassword } from "../../api.ts";
import { MEDIA_MD_UP } from "../../ui/breakpoints.ts";
import Button from "../../ui/Button.tsx";
import { Dialog, Sheet } from "../../ui/Dialog.tsx";
import Field from "../../ui/Field.tsx";
import { useMediaQuery } from "../../ui/useMediaQuery.ts";
import { toApiError } from "../../utils.ts";

const MIN_LENGTH = 12;
const MAX_LENGTH = 1024;

interface ChangePasswordDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** After the change: this browser keeps a new session, the others are out. */
  onChanged: () => void;
}

interface Errors {
  current?: string;
  next?: string;
  confirm?: string;
  form?: string;
}

/**
 * Current, new and confirmation (contracts/ui.md §3). The form only exists
 * while the dialog is open, so closing it always discards the typed passwords.
 */
function ChangePasswordDialog({
  open,
  onOpenChange,
  onChanged,
}: ChangePasswordDialogProps) {
  const isMedium = useMediaQuery(MEDIA_MD_UP);
  const Surface = isMedium ? Dialog : Sheet;
  return (
    <Surface open={open} onOpenChange={onOpenChange} title="Change password">
      {open && (
        <ChangePasswordForm
          onCancel={() => onOpenChange(false)}
          onChanged={onChanged}
        />
      )}
    </Surface>
  );
}

function ChangePasswordForm({
  onCancel,
  onChanged,
}: {
  onCancel: () => void;
  onChanged: () => void;
}) {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [errors, setErrors] = useState<Errors>({});
  const [busy, setBusy] = useState(false);

  function validate(): Errors {
    const found: Errors = {};
    if (current === "") {
      found.current = "Enter your current password.";
    }
    if (next.length < MIN_LENGTH || next.length > MAX_LENGTH) {
      found.next = `Use ${MIN_LENGTH} to ${MAX_LENGTH} characters.`;
    }
    if (confirm !== next) {
      found.confirm = "The new passwords do not match.";
    }
    return found;
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) {
      return;
    }
    const found = validate();
    setErrors(found);
    if (Object.keys(found).length > 0) {
      return;
    }
    setBusy(true);
    try {
      // The API stays the authority: it checks both passwords again.
      await changePassword(current, next);
      setCurrent("");
      setNext("");
      setConfirm("");
      onChanged();
    } catch (caught) {
      const apiError = toApiError(caught);
      if (apiError.code === "invalid_credentials") {
        setCurrent("");
        setErrors({ current: "Current password is incorrect." });
      } else if (apiError.code === "too_many_attempts") {
        setErrors({ form: "Too many attempts. Try again in a few minutes." });
      } else if (apiError.fieldMessage("new_password")) {
        setErrors({ next: apiError.fieldMessage("new_password") });
      } else if (apiError.code === "network_error") {
        setErrors({
          form: "Could not reach AutoPublisher. Try again in a moment.",
        });
      } else {
        setErrors({ form: "The password was not changed. Try again." });
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <form
      className="ap-change-password"
      aria-label="Change password"
      onSubmit={(event) => void handleSubmit(event)}
      noValidate
    >
      <Field label="Current password" error={errors.current}>
        {(control) => (
          <input
            {...control}
            type="password"
            autoComplete="current-password"
            value={current}
            onChange={(event) => setCurrent(event.target.value)}
          />
        )}
      </Field>
      <Field
        label="New password"
        hint={`At least ${MIN_LENGTH} characters.`}
        error={errors.next}
      >
        {(control) => (
          <input
            {...control}
            type="password"
            autoComplete="new-password"
            value={next}
            onChange={(event) => setNext(event.target.value)}
          />
        )}
      </Field>
      <Field label="Confirm new password" error={errors.confirm}>
        {(control) => (
          <input
            {...control}
            type="password"
            autoComplete="new-password"
            value={confirm}
            onChange={(event) => setConfirm(event.target.value)}
          />
        )}
      </Field>
      {errors.form && (
        <p className="error" role="alert">
          {errors.form}
        </p>
      )}
      <div className="ap-change-password__actions">
        <Button variant="primary" type="submit" loading={busy}>
          Change password
        </Button>
        <Button variant="ghost" onClick={onCancel}>
          Cancel
        </Button>
      </div>
    </form>
  );
}

export default ChangePasswordDialog;
