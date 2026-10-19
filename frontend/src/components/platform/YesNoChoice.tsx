import ChoiceGroup from "../../ui/ChoiceGroup.tsx";

interface YesNoChoiceProps {
  legend: string;
  /** null: not declared yet (nothing is preselected). */
  value: boolean | null;
  onChange: (value: boolean) => void;
  disabled?: boolean;
}

/** A required yes/no declaration as a horizontal radio group. */
function YesNoChoice({
  legend,
  value,
  onChange,
  disabled = false,
}: YesNoChoiceProps) {
  return (
    <ChoiceGroup
      legend={legend}
      orientation="horizontal"
      choices={[
        { value: "yes", label: "Yes" },
        { value: "no", label: "No" },
      ]}
      value={value === null ? null : value ? "yes" : "no"}
      onChange={(choice) => onChange(choice === "yes")}
      disabled={disabled}
    />
  );
}

export default YesNoChoice;
