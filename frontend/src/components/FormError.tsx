import type { ApiError } from "../api.ts";

interface FormErrorProps {
  error: ApiError | null;
  fields: string[];
}

/** Shows the general error message unless it is already shown next to a field. */
export function FormError({ error, fields }: FormErrorProps) {
  if (!error) {
    return null;
  }
  const shownNextToField = fields.some((field) => error.fieldMessage(field));
  if (shownNextToField) {
    return null;
  }
  return (
    <p className="error" role="alert">
      {error.message}
    </p>
  );
}
