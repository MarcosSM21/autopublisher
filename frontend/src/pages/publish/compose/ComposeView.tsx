import { useEffect, useMemo, useState } from "react";
import type { ApiError } from "../../../api.ts";
import type { Content, DistributionPreset, Project } from "../../../types.ts";
import Button from "../../../ui/Button.tsx";
import PageActions from "../../../ui/PageActions.tsx";
import { presetSelection, type Destination } from "../destinations.ts";
import {
  customFieldId,
  destinationRowId,
  DESTINATIONS_ID,
  type SummaryItem,
} from "../final-action.ts";
import ErrorSummary from "../review/ErrorSummary.tsx";
import { commonFromMedia, type CustomText } from "../snapshot.ts";
import type { PublishTaskController } from "../usePublishTask.ts";
import CommonContent from "./CommonContent.tsx";
import DestinationCustomize from "./DestinationCustomize.tsx";
import DestinationList from "./DestinationList.tsx";
import PresetPicker from "./PresetPicker.tsx";

const TARGET_FIELD = /^targets\.(\d+)\.(title|description|hashtags)_override$/;

/** A rejected create, as summary links to the destination or field. */
function createErrorItems(
  error: ApiError,
  list: readonly Destination[],
): SummaryItem[] {
  const name = (id: number) =>
    list.find((item) => item.accountId === id)?.name ?? "A destination";
  const items = error.fields.map((field): SummaryItem => {
    const match = TARGET_FIELD.exec(field.field);
    if (match) {
      return {
        target: customFieldId(Number(match[1]), match[2]),
        text: `${name(Number(match[1]))}: ${field.message}`,
      };
    }
    if (field.account_id !== undefined) {
      return {
        target: destinationRowId(field.account_id),
        text: field.message,
      };
    }
    return { target: DESTINATIONS_ID, text: field.message };
  });
  return items.length > 0
    ? items
    : [{ target: DESTINATIONS_ID, text: error.message }];
}

/** Messages a rejected create gives each destination as a whole. */
function rowErrors(error: ApiError | null): Record<number, string[]> {
  const rows: Record<number, string[]> = {};
  for (const field of error?.fields ?? []) {
    const id =
      field.account_id ?? Number(/^targets\.(\d+)$/.exec(field.field)?.[1]);
    if (Number.isInteger(id)) {
      rows[id] = [...(rows[id] ?? []), field.message];
    }
  }
  return rows;
}

interface ComposeViewProps {
  task: PublishTaskController;
  project: Project;
  /** null: a text post (no per-destination Customize before Continue, C3). */
  media: Content | null;
  presets: DistributionPreset[];
  onPresetsChange: (presets: DistributionPreset[]) => void;
}

/**
 * Compose: destinations, presets and content, all local until Continue
 * (spec FR-019). Continue creates the Drafts at once, or none.
 */
function ComposeView({
  task,
  project,
  media,
  presets,
  onPresetsChange,
}: ComposeViewProps) {
  const { compose, phase } = task.state;
  const creating = phase === "creating";
  // The open customization; a rejected field opens its destination's form
  // until the user opens or closes one (derived, not an effect).
  const createError = compose.createError;
  const [manualOpen, setManualOpen] = useState<{
    id: number | null;
    after: ApiError | null;
  }>({ id: null, after: null });
  const errorField = createError?.fields
    .map((item) => TARGET_FIELD.exec(item.field))
    .find((match) => match !== null);
  const openCustom =
    manualOpen.after === createError || !errorField
      ? manualOpen.id
      : Number(errorField[1]);
  const setOpenCustom = (id: number | null) =>
    setManualOpen({ id, after: createError });
  const selectedDestinations = task.destinations.filter((destination) =>
    compose.selected.includes(destination.accountId),
  );

  // Leaving with local input asks first (nothing is saved before Continue).
  const initialCommon = useMemo(() => commonFromMedia(media), [media]);
  const dirty =
    compose.selected.length > 0 ||
    Object.keys(compose.custom).length > 0 ||
    compose.common.description !== initialCommon.description ||
    compose.common.hashtags !== initialCommon.hashtags;
  useEffect(() => {
    if (!dirty) {
      return;
    }
    const warn = (event: BeforeUnloadEvent) => event.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  function toggle(accountId: number) {
    if (compose.selected.includes(accountId)) {
      const custom = { ...compose.custom };
      delete custom[accountId];
      task.changeCompose({
        selected: compose.selected.filter((id) => id !== accountId),
        custom,
      });
      if (openCustom === accountId) {
        setOpenCustom(null);
      }
    } else {
      const order = task.destinations.map((item) => item.accountId);
      task.changeCompose({
        selected: [...compose.selected, accountId].sort(
          (a, b) => order.indexOf(a) - order.indexOf(b),
        ),
      });
    }
  }

  function applyPreset(preset: DistributionPreset) {
    const { selected, skipped } = presetSelection(
      preset.account_ids,
      task.destinations,
      task.context?.health ?? [],
    );
    task.changeCompose({
      selected,
      custom: Object.fromEntries(
        Object.entries(compose.custom).filter(([id]) =>
          selected.includes(Number(id)),
        ),
      ),
      presetNotice: { preset: preset.name, skipped },
    });
    setOpenCustom(null);
  }

  function customize(accountId: number, custom: CustomText | null) {
    const next = { ...compose.custom };
    if (custom === null || Object.keys(custom).length === 0) {
      delete next[accountId];
    } else {
      next[accountId] = custom;
    }
    task.changeCompose({ custom: next });
  }

  const summaryItems = createError
    ? createErrorItems(createError, task.destinations)
    : task.summary;

  return (
    <div className="ap-compose" aria-busy={creating || undefined}>
      <ErrorSummary items={summaryItems} />
      <DestinationList
        destinations={task.destinations}
        selected={compose.selected}
        onToggle={toggle}
        onAddToTask={task.addToTask}
        errors={rowErrors(createError)}
        disabled={creating}
        accountsPath={`/p/${project.id}/accounts`}
      />
      <PresetPicker
        projectId={project.id}
        presets={presets}
        selected={compose.selected}
        notice={compose.presetNotice}
        disabled={creating}
        onApply={applyPreset}
        onPresetsChange={onPresetsChange}
      />
      <CommonContent
        common={compose.common}
        onChange={(common) => task.changeCompose({ common })}
        disabled={creating}
        textPost={media === null}
      >
        {media && (
          <DestinationCustomize
            destinations={selectedDestinations}
            common={compose.common}
            custom={compose.custom}
            mediaTitle={media.title}
            openId={openCustom}
            onOpen={setOpenCustom}
            onChange={customize}
            error={createError}
          />
        )}
      </CommonContent>
      <PageActions
        label="Publish actions"
        sticky
        primary={
          <Button
            variant="primary"
            loading={creating}
            onClick={() => void task.continueToReview()}
          >
            Continue
          </Button>
        }
      />
    </div>
  );
}

export default ComposeView;
