/** The explicit choice to publish automatically at the scheduled time. */
export function AutoPublishConsent({
  checked,
  disabled,
  onChange,
}: {
  checked: boolean;
  disabled: boolean;
  onChange: (checked: boolean) => void;
}) {
  return (
    <>
      <label className="checkbox">
        <span>
          <input
            type="checkbox"
            checked={checked}
            disabled={disabled}
            onChange={(event) => onChange(event.target.checked)}
          />{" "}
          Publish automatically at this time
        </span>
      </label>
      {checked && (
        <p className="notice">
          AutoPublisher will upload this publication automatically when the time
          comes. It must be running at that time.
        </p>
      )}
    </>
  );
}
