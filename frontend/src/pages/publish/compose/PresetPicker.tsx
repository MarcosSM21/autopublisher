import { useState } from "react";
import type { DistributionPreset } from "../../../types.ts";
import Button from "../../../ui/Button.tsx";
import Field from "../../../ui/Field.tsx";
import type { PresetNotice } from "../usePublishTask.ts";
import PresetsDialog from "./PresetsDialog.tsx";

interface PresetPickerProps {
  projectId: number;
  presets: DistributionPreset[];
  selected: number[];
  notice: PresetNotice | null;
  disabled: boolean;
  onApply: (preset: DistributionPreset) => void;
  onPresetsChange: (presets: DistributionPreset[]) => void;
}

/**
 * A compact preset selector. Applying one replaces the selection; what it
 * could not select is listed with its reason. Saving and managing presets
 * happen in a secondary dialog.
 */
function PresetPicker({
  projectId,
  presets,
  selected,
  notice,
  disabled,
  onApply,
  onPresetsChange,
}: PresetPickerProps) {
  const [open, setOpen] = useState(false);
  return (
    <div className="ap-preset-picker">
      <div className="ap-preset-picker__row">
        {presets.length > 0 && (
          <Field label="Preset" className="ap-preset-picker__field">
            {(control) => (
              <select
                {...control}
                value=""
                disabled={disabled}
                onChange={(event) => {
                  const preset = presets.find(
                    (item) => item.id === Number(event.target.value),
                  );
                  if (preset) {
                    onApply(preset);
                  }
                }}
              >
                <option value="">Apply a preset…</option>
                {presets.map((preset) => (
                  <option key={preset.id} value={preset.id}>
                    {preset.name}
                  </option>
                ))}
              </select>
            )}
          </Field>
        )}
        <Button
          variant="ghost"
          disabled={disabled}
          onClick={() => setOpen(true)}
        >
          Save as preset
        </Button>
        {presets.length > 0 && (
          <Button
            variant="ghost"
            disabled={disabled}
            onClick={() => setOpen(true)}
          >
            Manage presets
          </Button>
        )}
      </div>
      {notice && (
        <div className="ap-notice" role="status">
          <p>
            Applied “{notice.preset}”.
            {notice.skipped.length > 0 &&
              ` ${notice.skipped.length} ${notice.skipped.length === 1 ? "destination" : "destinations"} skipped:`}
          </p>
          {notice.skipped.length > 0 && (
            <ul>
              {notice.skipped.map((item) => (
                <li key={item.accountId}>
                  {item.name} · {item.reason}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
      <PresetsDialog
        open={open}
        onOpenChange={setOpen}
        projectId={projectId}
        presets={presets}
        selected={selected}
        onChange={onPresetsChange}
      />
    </div>
  );
}

export default PresetPicker;
