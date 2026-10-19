import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import ChoiceGroup, { type Choice } from "./ChoiceGroup.tsx";
import Field from "./Field.tsx";

afterEach(cleanup);

describe("Field", () => {
  it("names the control by its label and describes it by hint and error", () => {
    render(
      <Field label="Caption" hint="Shown under the video." required>
        {(control) => <textarea {...control} />}
      </Field>,
    );
    const input = screen.getByRole("textbox", { name: /Caption/ });
    expect(input).toHaveAccessibleDescription("Shown under the video.");
    expect(input).toBeRequired();
    expect(input).not.toHaveAttribute("aria-invalid");
    cleanup();

    render(
      <Field label="Caption" hint="Shown under the video." error="Too long">
        {(control) => <input {...control} />}
      </Field>,
    );
    const invalid = screen.getByRole("textbox", { name: "Caption" });
    expect(invalid).toBeInvalid();
    expect(invalid).toHaveAccessibleDescription(
      "Shown under the video. Too long",
    );
  });
});

type View = "list" | "calendar";
const VIEWS: Choice<View>[] = [
  { value: "list", label: "List" },
  { value: "calendar", label: "Calendar" },
];

function Controlled({
  variant,
  onChange,
}: {
  variant: "radios" | "switch";
  onChange: (value: View) => void;
}) {
  const [value, setValue] = useState<View | null>(null);
  return (
    <ChoiceGroup
      legend="View"
      choices={VIEWS}
      value={value}
      variant={variant}
      orientation="horizontal"
      onChange={(next) => {
        setValue(next);
        onChange(next);
      }}
    />
  );
}

describe("ChoiceGroup", () => {
  it.each(["radios", "switch"] as const)(
    "%s: a named radio group chosen by click or keyboard, nothing chosen by default",
    async (variant) => {
      const onChange = vi.fn();
      const user = userEvent.setup();
      render(<Controlled variant={variant} onChange={onChange} />);

      expect(screen.getByRole("group", { name: "View" })).toBeInTheDocument();
      const list = screen.getByRole("radio", { name: "List" });
      const calendar = screen.getByRole("radio", { name: "Calendar" });
      expect(list).not.toBeChecked();
      expect(calendar).not.toBeChecked();

      await user.click(list);
      expect(list).toBeChecked();
      await user.keyboard("{ArrowRight}");
      expect(calendar).toBeChecked();
      expect(onChange).toHaveBeenLastCalledWith("calendar");
    },
  );
});
