import { useId, useState, type FormEvent } from "react";
import type { PublicationUpdate } from "../../../api.ts";
import type { Publication } from "../../../types.ts";
import Button from "../../../ui/Button.tsx";
import { Dialog } from "../../../ui/Dialog.tsx";
import Field from "../../../ui/Field.tsx";
import { accountName, parseHashtags, toApiError } from "../../../utils.ts";
import { hashtagsText, usesTitle } from "../snapshot.ts";

interface EditContentDialogProps {
  /** Every Draft still to finish. */
  drafts: Publication[];
  /** The Draft to customize; null: choose the destinations to change. */
  single: Publication | null;
  onClose: () => void;
  onSave: (ids: number[], changes: PublicationUpdate) => Promise<void>;
  /** A failed save stays visible until the dialog closes (discarded). */
  onFailedChange: (failed: boolean) => void;
}

/**
 * Edits the content of one destination (`Customize`) or of a set chosen
 * explicitly (`Edit for these destinations`), showing which destinations will
 * change. Saving is explicit and writes only those Posts, as explicit text.
 */
function EditContentDialog({
  drafts,
  single,
  onClose,
  onSave,
  onFailedChange,
}: EditContentDialogProps) {
  const listId = useId();
  const first = single ?? drafts[0];
  // The set is chosen explicitly: nothing is preselected (FR-034).
  const [chosen, setChosen] = useState<number[]>(single ? [single.id] : []);
  const [caption, setCaption] = useState(first?.description ?? "");
  const [hashtags, setHashtags] = useState(hashtagsText(first?.hashtags ?? []));
  const [title, setTitle] = useState(first?.title ?? "");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const withTitle = single !== null && usesTitle(single.account.platform);
  const changing = drafts.filter((post) => chosen.includes(post.id));

  async function save(event: FormEvent) {
    event.preventDefault();
    if (changing.length === 0) {
      setError("Choose at least one destination.");
      return;
    }
    setSaving(true);
    setError(null);
    const changes: PublicationUpdate = {
      description_override: caption,
      hashtags_override: parseHashtags(hashtags),
      ...(withTitle ? { title_override: title } : {}),
    };
    try {
      await onSave(
        changing.map((post) => post.id),
        changes,
      );
      onFailedChange(false);
      onClose();
    } catch (caught) {
      setError(toApiError(caught).message);
      onFailedChange(true);
      setSaving(false);
    }
  }

  function close(open: boolean) {
    if (!open) {
      // Closing discards the change that couldn't be saved.
      onFailedChange(false);
      onClose();
    }
  }

  return (
    <Dialog
      open
      onOpenChange={close}
      title={
        single
          ? `Customize ${accountName(single.account)}`
          : "Edit for these destinations"
      }
      footer={
        <>
          <Button
            type="submit"
            form={listId}
            variant="primary"
            loading={saving}
          >
            Save
          </Button>
          <Button onClick={() => close(false)}>Cancel</Button>
        </>
      }
    >
      <form id={listId} className="ap-edit-content" onSubmit={save} noValidate>
        {!single && (
          <fieldset className="ap-choice-group">
            <legend className="ap-choice-group__legend">
              Destinations to change
            </legend>
            {drafts.map((post) => (
              <label key={post.id} className="ap-check">
                <input
                  type="checkbox"
                  checked={chosen.includes(post.id)}
                  onChange={(event) =>
                    setChosen((current) =>
                      event.target.checked
                        ? [...current, post.id]
                        : current.filter((id) => id !== post.id),
                    )
                  }
                />
                <span>{accountName(post.account)}</span>
              </label>
            ))}
          </fieldset>
        )}
        {withTitle && (
          <Field label="Title">
            {(control) => (
              <input
                {...control}
                value={title}
                onChange={(event) => setTitle(event.target.value)}
              />
            )}
          </Field>
        )}
        <Field label="Caption">
          {(control) => (
            <textarea
              {...control}
              rows={4}
              value={caption}
              onChange={(event) => setCaption(event.target.value)}
            />
          )}
        </Field>
        <Field label="Hashtags">
          {(control) => (
            <input
              {...control}
              value={hashtags}
              onChange={(event) => setHashtags(event.target.value)}
            />
          )}
        </Field>
        {!single && (
          <p className="ap-meta" aria-live="polite">
            {changing.length > 0
              ? `Will change: ${changing.map((post) => accountName(post.account)).join(", ")}`
              : "No destination will change."}
          </p>
        )}
        {error && (
          <p className="ap-field__error" role="alert">
            {error}
          </p>
        )}
      </form>
    </Dialog>
  );
}

export default EditContentDialog;
