import { useId, useState, type FormEvent } from "react";
import { ApiError, type AccountInput } from "../api.ts";
import { PLATFORMS, platformLabel, type Platform } from "../types.ts";
import { toApiError } from "../utils.ts";
import { FormError } from "./FormError.tsx";
import { FieldMessage } from "./ProjectForm.tsx";

interface AccountFormProps {
  label: string;
  mode: "create" | "edit";
  initialValues?: AccountInput;
  submitLabel: string;
  onSubmit: (values: AccountInput) => Promise<void>;
  onCancel?: () => void;
  resetOnSuccess?: boolean;
}

function AccountForm({
  label,
  mode,
  initialValues,
  submitLabel,
  onSubmit,
  onCancel,
  resetOnSuccess = false,
}: AccountFormProps) {
  const id = useId();
  const [platform, setPlatform] = useState<string>(
    initialValues?.platform ?? "",
  );
  const [handle, setHandle] = useState(initialValues?.handle ?? "");
  const [displayName, setDisplayName] = useState(
    initialValues?.display_name ?? "",
  );
  const [error, setError] = useState<ApiError | null>(null);
  const [saving, setSaving] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (mode === "create" && platform === "") {
      // The backend also rejects a missing platform, but its message lists
      // internal values, so the form reports it in user-facing terms instead.
      setError(
        new ApiError(0, "validation_error", "Select a platform.", [
          { field: "platform", message: "Select a platform." },
        ]),
      );
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await onSubmit({
        platform: platform as Platform,
        handle,
        display_name: displayName === "" ? null : displayName,
      });
      if (resetOnSuccess) {
        setPlatform("");
        setHandle("");
        setDisplayName("");
      }
    } catch (caught) {
      setError(toApiError(caught));
    } finally {
      setSaving(false);
    }
  }

  return (
    <form aria-label={label} onSubmit={handleSubmit} noValidate>
      <label htmlFor={`${id}-platform`}>Platform</label>
      {mode === "create" ? (
        <select
          id={`${id}-platform`}
          value={platform}
          onChange={(event) => setPlatform(event.target.value)}
        >
          <option value="">Select a platform</option>
          {PLATFORMS.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
      ) : (
        <input
          id={`${id}-platform`}
          value={platformLabel(platform as Platform)}
          readOnly
        />
      )}
      <FieldMessage error={error} field="platform" />
      <label htmlFor={`${id}-handle`}>Handle</label>
      <input
        id={`${id}-handle`}
        value={handle}
        onChange={(event) => setHandle(event.target.value)}
        placeholder="@handle"
      />
      <FieldMessage error={error} field="handle" />
      <label htmlFor={`${id}-display-name`}>Display name</label>
      <input
        id={`${id}-display-name`}
        value={displayName}
        onChange={(event) => setDisplayName(event.target.value)}
      />
      <FieldMessage error={error} field="display_name" />
      <FormError
        error={error}
        fields={["platform", "handle", "display_name"]}
      />
      <div className="actions">
        <button type="submit" disabled={saving}>
          {submitLabel}
        </button>
        {onCancel && (
          <button type="button" onClick={onCancel}>
            Cancel
          </button>
        )}
      </div>
    </form>
  );
}

export default AccountForm;
