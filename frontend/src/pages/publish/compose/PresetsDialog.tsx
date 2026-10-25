import { useState, type FormEvent } from "react";
import {
  createDistributionPreset,
  deleteDistributionPreset,
  listDistributionPresets,
  updateDistributionPreset,
  type ApiError,
} from "../../../api.ts";
import type { DistributionPreset } from "../../../types.ts";
import Button from "../../../ui/Button.tsx";
import { Dialog } from "../../../ui/Dialog.tsx";
import Field from "../../../ui/Field.tsx";
import { toApiError } from "../../../utils.ts";

interface PresetsDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  projectId: number;
  presets: DistributionPreset[];
  /** The destinations selected in Compose (account ids). */
  selected: number[];
  onChange: (presets: DistributionPreset[]) => void;
}

type Target = "new" | number;

/** The message of a preset request: its field errors, or the error itself. */
function messages(error: ApiError): string[] {
  const fields = error.fields.filter((field) =>
    ["name", "account_ids"].includes(field.field),
  );
  return fields.length > 0
    ? fields.map((field) => field.message)
    : [error.message];
}

/**
 * Save the selection as a preset, rename a preset, give it the selected
 * destinations or delete it. A secondary dialog: presets only name a set of
 * destinations, so nothing here touches a Post.
 */
function PresetsDialog({
  open,
  onOpenChange,
  projectId,
  presets,
  selected,
  onChange,
}: PresetsDialogProps) {
  const [name, setName] = useState("");
  const [renaming, setRenaming] = useState<{ id: number; name: string } | null>(
    null,
  );
  const [deleting, setDeleting] = useState<number | null>(null);
  const [error, setError] = useState<{
    target: Target;
    error: ApiError;
  } | null>(null);
  const [busy, setBusy] = useState(false);

  async function run(target: Target, action: () => Promise<void>) {
    setBusy(true);
    setError(null);
    try {
      await action();
    } catch (caught) {
      setError({ target, error: toApiError(caught) });
    } finally {
      setBusy(false);
    }
  }

  /** New or renamed presets take the backend's order (by name). */
  const reload = async () => onChange(await listDistributionPresets(projectId));

  function saveNew(event: FormEvent) {
    event.preventDefault();
    void run("new", async () => {
      await createDistributionPreset(projectId, {
        name,
        account_ids: selected,
      });
      setName("");
      await reload();
    });
  }

  function saveName(event: FormEvent) {
    event.preventDefault();
    if (renaming === null) {
      return;
    }
    void run(renaming.id, async () => {
      await updateDistributionPreset(renaming.id, { name: renaming.name });
      setRenaming(null);
      await reload();
    });
  }

  const errorFor = (target: Target) =>
    error?.target === target ? messages(error.error).join(" ") : null;
  const count = (ids: number[]) =>
    `${ids.length} ${ids.length === 1 ? "destination" : "destinations"}`;

  return (
    <Dialog open={open} onOpenChange={onOpenChange} title="Presets">
      <div className="ap-presets">
        <form className="ap-presets__new" onSubmit={saveNew} noValidate>
          <Field
            label="Preset name"
            hint={`Saves the ${count(selected)} selected now.`}
            error={errorFor("new")}
          >
            {(control) => (
              <input
                {...control}
                value={name}
                onChange={(event) => setName(event.target.value)}
              />
            )}
          </Field>
          <Button type="submit" variant="primary" loading={busy}>
            Save as preset
          </Button>
        </form>

        {presets.length > 0 && (
          <ul className="ap-presets__list" aria-label="Presets">
            {presets.map((preset) => (
              <li key={preset.id} className="ap-presets__item">
                {renaming?.id === preset.id ? (
                  <form className="ap-form" onSubmit={saveName} noValidate>
                    <Field
                      label={`New name for ${preset.name}`}
                      error={errorFor(preset.id)}
                    >
                      {(control) => (
                        <input
                          {...control}
                          value={renaming.name}
                          onChange={(event) =>
                            setRenaming({
                              id: preset.id,
                              name: event.target.value,
                            })
                          }
                        />
                      )}
                    </Field>
                    <div className="ap-presets__actions">
                      <Button type="submit" variant="primary" loading={busy}>
                        Save name
                      </Button>
                      <Button onClick={() => setRenaming(null)}>Cancel</Button>
                    </div>
                  </form>
                ) : deleting === preset.id ? (
                  <div className="ap-presets__confirm">
                    <p>
                      Delete “{preset.name}”? Accounts and posts are not
                      affected.
                    </p>
                    <div className="ap-presets__actions">
                      <Button
                        variant="danger"
                        loading={busy}
                        onClick={() =>
                          void run(preset.id, async () => {
                            await deleteDistributionPreset(preset.id);
                            setDeleting(null);
                            onChange(
                              presets.filter((item) => item.id !== preset.id),
                            );
                          })
                        }
                      >
                        Delete
                      </Button>
                      <Button onClick={() => setDeleting(null)}>Keep</Button>
                    </div>
                  </div>
                ) : (
                  <>
                    <p className="ap-presets__name">
                      {preset.name}{" "}
                      <span className="ap-meta">
                        {count(preset.account_ids)}
                      </span>
                    </p>
                    <div className="ap-presets__actions">
                      <Button
                        variant="ghost"
                        aria-label={`Rename ${preset.name}`}
                        disabled={busy}
                        onClick={() =>
                          setRenaming({ id: preset.id, name: preset.name })
                        }
                      >
                        Rename
                      </Button>
                      <Button
                        variant="ghost"
                        aria-label={`Use the selected destinations for ${preset.name}`}
                        disabled={busy}
                        onClick={() =>
                          void run(preset.id, async () => {
                            const saved = await updateDistributionPreset(
                              preset.id,
                              { account_ids: selected },
                            );
                            onChange(
                              presets.map((item) =>
                                item.id === saved.id ? saved : item,
                              ),
                            );
                          })
                        }
                      >
                        Use selected destinations
                      </Button>
                      <Button
                        variant="ghost"
                        aria-label={`Delete ${preset.name}`}
                        disabled={busy}
                        onClick={() => setDeleting(preset.id)}
                      >
                        Delete
                      </Button>
                    </div>
                    {errorFor(preset.id) && (
                      <p className="ap-field__error">{errorFor(preset.id)}</p>
                    )}
                  </>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>
    </Dialog>
  );
}

export default PresetsDialog;
