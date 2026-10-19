import { useId, type ReactNode } from "react";

/** What the control inside a Field must spread to be described by it. */
export interface FieldControlProps {
  id: string;
  "aria-describedby"?: string;
  "aria-invalid"?: true;
  required?: boolean;
}

interface FieldProps {
  label: ReactNode;
  /** Short help shown under the label. */
  hint?: ReactNode;
  /** Inline error; marks the control invalid and describes it. */
  error?: string | null;
  required?: boolean;
  /** Forces the control id (e.g. so an error summary can link to it). */
  id?: string;
  /** Renders the control with the props that tie it to the label, hint and error. */
  children: (control: FieldControlProps) => ReactNode;
  className?: string;
}

/**
 * Label, hint, required marker and inline error around one control. The control
 * gets its accessible name from the label and its description from the hint and
 * the error, so assistive technology reads all three.
 */
function Field({
  label,
  hint,
  error,
  required = false,
  id,
  children,
  className,
}: FieldProps) {
  const generated = useId();
  const controlId = id ?? generated;
  const hintId = `${controlId}-hint`;
  const errorId = `${controlId}-error`;
  const describedBy =
    [hint ? hintId : null, error ? errorId : null].filter(Boolean).join(" ") ||
    undefined;

  return (
    <div className={["ap-field", className].filter(Boolean).join(" ")}>
      <label htmlFor={controlId} className="ap-field__label">
        {label}
        {required && (
          <span className="ap-field__required" aria-hidden="true">
            {" "}
            *
          </span>
        )}
      </label>
      {hint && (
        <p id={hintId} className="ap-field__hint">
          {hint}
        </p>
      )}
      {children({
        id: controlId,
        "aria-describedby": describedBy,
        ...(error ? { "aria-invalid": true as const } : {}),
        ...(required ? { required: true } : {}),
      })}
      {error && (
        <p id={errorId} className="ap-field__error">
          {error}
        </p>
      )}
    </div>
  );
}

export default Field;
