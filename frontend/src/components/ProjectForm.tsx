import { useId, useState, type FormEvent } from "react";
import type { ApiError, ProjectInput } from "../api.ts";
import { toApiError } from "../utils.ts";
import { FormError } from "./FormError.tsx";

interface ProjectFormProps {
  label: string;
  initialValues?: ProjectInput;
  submitLabel: string;
  onSubmit: (values: ProjectInput) => Promise<void>;
  onCancel?: () => void;
  resetOnSuccess?: boolean;
}

function ProjectForm({
  label,
  initialValues,
  submitLabel,
  onSubmit,
  onCancel,
  resetOnSuccess = false,
}: ProjectFormProps) {
  const id = useId();
  const [name, setName] = useState(initialValues?.name ?? "");
  const [description, setDescription] = useState(
    initialValues?.description ?? "",
  );
  const [error, setError] = useState<ApiError | null>(null);
  const [saving, setSaving] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaving(true);
    setError(null);
    try {
      await onSubmit({
        name,
        description: description === "" ? null : description,
      });
      if (resetOnSuccess) {
        setName("");
        setDescription("");
      }
    } catch (caught) {
      setError(toApiError(caught));
    } finally {
      setSaving(false);
    }
  }

  return (
    <form aria-label={label} onSubmit={handleSubmit} noValidate>
      <label htmlFor={`${id}-name`}>Name</label>
      <input
        id={`${id}-name`}
        value={name}
        onChange={(event) => setName(event.target.value)}
        aria-invalid={error?.fieldMessage("name") ? true : undefined}
      />
      <FieldMessage error={error} field="name" />
      <label htmlFor={`${id}-description`}>Description</label>
      <textarea
        id={`${id}-description`}
        value={description}
        onChange={(event) => setDescription(event.target.value)}
        rows={2}
      />
      <FieldMessage error={error} field="description" />
      <FormError error={error} fields={["name", "description"]} />
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

function FieldMessage({
  error,
  field,
}: {
  error: ApiError | null;
  field: string;
}) {
  const message = error?.fieldMessage(field);
  return message ? <span className="error">{message}</span> : null;
}

export { FieldMessage };
export default ProjectForm;
