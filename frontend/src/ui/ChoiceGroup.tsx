import { useId, type ReactNode } from "react";

export interface Choice<T extends string> {
  value: T;
  label: ReactNode;
  /** Shown under the label (vertical groups only). */
  description?: ReactNode;
  disabled?: boolean;
}

interface ChoiceGroupProps<T extends string> {
  /** The group's visible question; the legend of the fieldset. */
  legend: ReactNode;
  /** Hides the legend visually (it stays the accessible name), e.g. a view switch. */
  hideLegend?: boolean;
  choices: Choice<T>[];
  /** null: nothing chosen yet (no default is invented). */
  value: T | null;
  onChange: (value: T) => void;
  orientation?: "vertical" | "horizontal";
  /** "switch": segmented view switch (e.g. List | Calendar). */
  variant?: "radios" | "switch";
  error?: string | null;
  disabled?: boolean;
  className?: string;
}

/**
 * One choice among a few: native radios in a fieldset, so arrow keys, the legend
 * and the selection behave as the platform expects. The switch variant looks
 * segmented but stays a radio group.
 */
function ChoiceGroup<T extends string>({
  legend,
  hideLegend = false,
  choices,
  value,
  onChange,
  orientation = "vertical",
  variant = "radios",
  error,
  disabled = false,
  className,
}: ChoiceGroupProps<T>) {
  const name = useId();
  const errorId = `${name}-error`;
  const classes = [
    "ap-choice-group",
    `ap-choice-group--${variant === "switch" ? "switch" : orientation}`,
    className,
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <fieldset
      className={classes}
      disabled={disabled}
      aria-describedby={error ? errorId : undefined}
      aria-invalid={error ? true : undefined}
    >
      <legend
        className={
          hideLegend ? "ap-visually-hidden" : "ap-choice-group__legend"
        }
      >
        {legend}
      </legend>
      <div className="ap-choice-group__options">
        {choices.map((choice) => (
          <label
            key={choice.value}
            className={
              choice.value === value
                ? "ap-choice ap-choice--selected"
                : "ap-choice"
            }
          >
            <input
              type="radio"
              name={name}
              value={choice.value}
              checked={choice.value === value}
              disabled={choice.disabled}
              onChange={() => onChange(choice.value)}
            />
            <span className="ap-choice__text">
              <span className="ap-choice__label">{choice.label}</span>
              {choice.description && variant !== "switch" && (
                <span className="ap-choice__description">
                  {choice.description}
                </span>
              )}
            </span>
          </label>
        ))}
      </div>
      {error && (
        <p id={errorId} className="ap-field__error">
          {error}
        </p>
      )}
    </fieldset>
  );
}

export default ChoiceGroup;
