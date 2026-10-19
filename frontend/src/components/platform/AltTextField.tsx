import { useState } from "react";
import Field from "../../ui/Field.tsx";

interface AltTextFieldProps {
  /** The saved alt text. */
  saved: string | null;
  maxLength: number;
  hint: string;
  disabled?: boolean;
  /** Called on blur, only when the text differs from the saved one. */
  onCommit: (value: string) => void;
}

/** Optional alt text, typed freely and saved when the field loses focus. */
function AltTextField({
  saved,
  maxLength,
  hint,
  disabled = false,
  onCommit,
}: AltTextFieldProps) {
  const [draft, setDraft] = useState(saved ?? "");
  const [base, setBase] = useState(saved);
  // A different saved value (e.g. reloaded) replaces the draft.
  if (saved !== base) {
    setBase(saved);
    setDraft(saved ?? "");
  }
  return (
    <Field label="Alt text" hint={hint}>
      {(control) => (
        <>
          <textarea
            {...control}
            value={draft}
            maxLength={maxLength}
            rows={3}
            disabled={disabled}
            onChange={(event) => setDraft(event.target.value)}
            onBlur={() => {
              if (draft !== (saved ?? "")) {
                onCommit(draft);
              }
            }}
          />
          <span className="ap-meta">
            {draft.length}/{maxLength}
          </span>
        </>
      )}
    </Field>
  );
}

export default AltTextField;
