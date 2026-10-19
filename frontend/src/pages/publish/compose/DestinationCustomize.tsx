import type { ApiError } from "../../../api.ts";
import Button from "../../../ui/Button.tsx";
import Field from "../../../ui/Field.tsx";
import type { Destination } from "../destinations.ts";
import { customFieldId } from "../final-action.ts";
import {
  usesTitle,
  type CommonText,
  type CustomText,
  type TextField,
} from "../snapshot.ts";

const LABELS: Record<TextField, string> = {
  title: "Title",
  description: "Caption",
  hashtags: "Hashtags",
};

interface DestinationCustomizeProps {
  destinations: Destination[];
  common: CommonText;
  custom: Record<number, CustomText>;
  mediaTitle: string | null;
  /** The destination whose form is open (one at a time). */
  openId: number | null;
  onOpen: (accountId: number | null) => void;
  onChange: (accountId: number, custom: CustomText | null) => void;
  error: ApiError | null;
}

function fieldsOf(destination: Destination): TextField[] {
  return usesTitle(destination.platform)
    ? ["title", "description", "hashtags"]
    : ["description", "hashtags"];
}

/**
 * Per-destination customization as progressive disclosure: one row per
 * selected destination and at most one form open. Only edited fields are kept;
 * the title exists only where the platform sends one (YouTube).
 */
function DestinationCustomize({
  destinations,
  common,
  custom,
  mediaTitle,
  openId,
  onOpen,
  onChange,
  error,
}: DestinationCustomizeProps) {
  if (destinations.length === 0) {
    return null;
  }
  const inherited = (field: TextField) =>
    field === "title" ? (mediaTitle ?? "") : common[field];
  return (
    <ul className="ap-customize-list" aria-label="Customize by destination">
      {destinations.map((destination) => {
        const id = destination.accountId;
        const fields = custom[id] ?? {};
        const customized = Object.keys(fields).length > 0;
        const open = openId === id;
        const regionId = `publish-customize-${id}`;
        return (
          <li key={id} className="ap-customize">
            <div className="ap-customize__row">
              <span className="ap-customize__name">
                {destination.name}
                {customized && <span className="ap-meta"> · Customized</span>}
              </span>
              <Button
                variant="ghost"
                aria-expanded={open}
                aria-controls={regionId}
                aria-label={`Customize ${destination.name}`}
                onClick={() => onOpen(open ? null : id)}
              >
                Customize
              </Button>
            </div>
            {open && (
              <div id={regionId} className="ap-customize__form">
                {fieldsOf(destination).map((field) => {
                  const fieldId = customFieldId(id, field);
                  const value = fields[field] ?? inherited(field);
                  const change = (text: string) =>
                    onChange(id, { ...fields, [field]: text });
                  return (
                    <Field
                      key={field}
                      id={fieldId}
                      label={`${LABELS[field]} for ${destination.name}`}
                      error={error?.fieldMessage(
                        `targets.${id}.${field}_override`,
                      )}
                    >
                      {(control) =>
                        field === "description" ? (
                          <textarea
                            {...control}
                            rows={3}
                            value={value}
                            onChange={(event) => change(event.target.value)}
                          />
                        ) : (
                          <input
                            {...control}
                            value={value}
                            onChange={(event) => change(event.target.value)}
                          />
                        )
                      }
                    </Field>
                  );
                })}
                {customized && (
                  <Button variant="ghost" onClick={() => onChange(id, null)}>
                    Discard customization
                  </Button>
                )}
              </div>
            )}
          </li>
        );
      })}
    </ul>
  );
}

export default DestinationCustomize;
