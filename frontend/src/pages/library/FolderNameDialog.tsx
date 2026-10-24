import { useState, type FormEvent } from "react";
import { MAX_FOLDER_NAME_LENGTH } from "../../types.ts";
import Button from "../../ui/Button.tsx";
import { Dialog } from "../../ui/Dialog.tsx";
import Field from "../../ui/Field.tsx";
import { toApiError } from "../../utils.ts";

interface FolderNameDialogProps {
  /** "New folder" or "Rename folder". */
  title: string;
  submitLabel: string;
  initialName?: string;
  /** Saves the trimmed name; a rejection is shown inline. */
  onSubmit: (name: string) => Promise<void>;
  onClose: () => void;
}

/**
 * Create or rename a folder: one Name field, the backend's answer inline
 * (`folder_name_taken`, `folder_too_deep`, validation). Mounted while open, so
 * every opening starts from the initial name.
 */
function FolderNameDialog({
  title,
  submitLabel,
  initialName = "",
  onSubmit,
  onClose,
}: FolderNameDialogProps) {
  const [name, setName] = useState(initialName);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    const trimmed = name.trim();
    if (trimmed === "") {
      setError("Enter a folder name.");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await onSubmit(trimmed);
    } catch (caught) {
      const apiError = toApiError(caught);
      setError(apiError.fieldMessage("name") ?? apiError.message);
      setSaving(false);
    }
  }

  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open) {
          onClose();
        }
      }}
      title={title}
    >
      <form
        className="ap-folder-name-form"
        noValidate
        onSubmit={(event) => void handleSubmit(event)}
      >
        <Field label="Name" error={error} required>
          {(control) => (
            <input
              {...control}
              type="text"
              value={name}
              maxLength={MAX_FOLDER_NAME_LENGTH}
              autoComplete="off"
              onChange={(event) => setName(event.target.value)}
            />
          )}
        </Field>
        <div className="ap-folder-name-form__actions">
          <Button type="submit" variant="primary" loading={saving}>
            {submitLabel}
          </Button>
          <Button onClick={onClose}>Cancel</Button>
        </div>
      </form>
    </Dialog>
  );
}

export default FolderNameDialog;
