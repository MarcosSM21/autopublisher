import {
  useCallback,
  useEffect,
  useId,
  useState,
  type FormEvent,
  type KeyboardEvent,
} from "react";
import {
  createDistributionPreset,
  createPublications,
  deleteDistributionPreset,
  getContentUsage,
  listAccounts,
  listDistributionPresets,
  listPublications,
  updateDistributionPreset,
  type ApiError,
  type PublicationCreate,
  type PublicationOverrides,
} from "../api.ts";
import {
  type Account,
  type AssetPublication,
  type Content,
  type DistributionPreset,
  type Platform,
  type Project,
  type Publication,
  type PublishCheck,
  type TikTokMode,
} from "../types.ts";
import {
  accountName,
  blocksNewPublication,
  fromDateTimeLocalValue,
  hasPlatformOptions,
  isPublishable,
  isTikTokVideo,
  parseHashtags,
  publicationStatusLabel,
  PUBLISHING_PLATFORMS,
  toApiError,
} from "../utils.ts";
import { FormError } from "./FormError.tsx";
import { FieldMessage } from "./ProjectForm.tsx";
import {
  AutoPublishControls,
  PublicationPlatformOptions,
  PublishAction,
} from "./PublicationControls.tsx";
import { useLivePublication } from "./useLivePublication.ts";

/** Platforms whose publications use a title (a presentation rule, not a publisher one). */
const TITLE_PLATFORMS: Platform[] = ["youtube"];

type TextField = "title" | "description" | "hashtags";

const FIELD_LABELS: Record<TextField, string> = {
  title: "Title",
  description: "Description / caption",
  hashtags: "Hashtags",
};

/** Whether the user edited the field; untouched fields send no override. */
interface FieldState {
  edited: boolean;
  text: string;
}

type Customization = Partial<Record<TextField, FieldState>>;

function hashtagsText(tags: string[]): string {
  return tags.map((tag) => `#${tag}`).join(" ");
}

function contentText(content: Content, field: TextField): string {
  if (field === "hashtags") {
    return hashtagsText(content.hashtags);
  }
  return content[field] ?? "";
}

/** Only edited fields become overrides; an edited empty field is an explicit "" / []. */
function toOverrides(fields: Customization): PublicationOverrides {
  const overrides: PublicationOverrides = {};
  if (fields.title?.edited) {
    overrides.title_override = fields.title.text;
  }
  if (fields.description?.edited) {
    overrides.description_override = fields.description.text;
  }
  if (fields.hashtags?.edited) {
    overrides.hashtags_override = parseHashtags(fields.hashtags.text);
  }
  return overrides;
}

function isCustomized(customization: Customization | undefined): boolean {
  return Object.values(customization ?? {}).some((state) => state?.edited);
}

function textFields(account: Account): TextField[] {
  return TITLE_PLATFORMS.includes(account.platform)
    ? ["title", "description", "hashtags"]
    : ["description", "hashtags"];
}

interface DistributeProps {
  project: Project;
  content: Content;
  onOpenQueue: () => void;
}

function Distribute({ project, content, onOpenQueue }: DistributeProps) {
  const [accounts, setAccounts] = useState<Account[] | null>(null);
  const [usage, setUsage] = useState<AssetPublication[]>([]);
  const [presets, setPresets] = useState<DistributionPreset[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [created, setCreated] = useState<Publication[] | null>(null);

  const load = useCallback(
    () =>
      Promise.all([
        listAccounts(project.id),
        getContentUsage(content.id),
        listDistributionPresets(project.id),
      ])
        .then(([loadedAccounts, loadedUsage, loadedPresets]) => {
          setAccounts(loadedAccounts);
          setUsage(loadedUsage.publications);
          setPresets(loadedPresets);
          setLoadError(null);
        })
        .catch((caught: unknown) => setLoadError(toApiError(caught).message)),
    [project.id, content.id],
  );

  useEffect(() => {
    void load();
  }, [load]);

  if (loadError) {
    return (
      <p className="error" role="alert">
        {loadError}
      </p>
    );
  }
  if (!project.is_active) {
    return (
      <p className="muted">Reactivate the project to prepare publications.</p>
    );
  }
  if (!content.file_available) {
    return (
      <p className="muted">The media file of this content is not available.</p>
    );
  }
  if (accounts === null) {
    return null;
  }
  const activeAccounts = accounts.filter((account) => account.is_active);
  if (activeAccounts.length === 0) {
    return (
      <p className="muted">Add an active account to this project first.</p>
    );
  }
  if (created) {
    return (
      <DistributionResult
        project={project}
        created={created}
        onDistributeAgain={() => {
          setCreated(null);
          void load();
        }}
        onOpenQueue={onOpenQueue}
      />
    );
  }
  // Accounts with an active (non-history) publication of this content.
  const taken = new Set(
    usage
      .filter((publication) => blocksNewPublication(publication.status))
      .map((publication) => publication.account_id),
  );
  return (
    <DistributeForm
      project={project}
      content={content}
      accounts={accounts}
      taken={taken}
      presets={presets}
      onPresetsChange={setPresets}
      onCreated={setCreated}
    />
  );
}

function DistributeForm({
  project,
  content,
  accounts: projectAccounts,
  taken,
  presets,
  onPresetsChange,
  onCreated,
}: {
  project: Project;
  content: Content;
  /** All the project's accounts; only active ones can be chosen. */
  accounts: Account[];
  taken: Set<number>;
  presets: DistributionPreset[];
  onPresetsChange: (presets: DistributionPreset[]) => void;
  onCreated: (created: Publication[]) => void;
}) {
  const id = useId();
  const accounts = projectAccounts.filter((account) => account.is_active);
  const [selected, setSelected] = useState<number[]>([]);
  // What the last applied preset could not select, and why.
  const [presetNotice, setPresetNotice] = useState<{
    skipped: string[];
    empty: boolean;
  } | null>(null);
  const [common, setCommon] = useState<
    Record<"description" | "hashtags", FieldState>
  >({
    description: { edited: false, text: contentText(content, "description") },
    hashtags: { edited: false, text: contentText(content, "hashtags") },
  });
  const [customizations, setCustomizations] = useState<
    Record<number, Customization>
  >({});
  const [expanded, setExpanded] = useState<number[]>([]);
  const [when, setWhen] = useState<"prepare" | "schedule">("prepare");
  const [publishAt, setPublishAt] = useState("");
  const [error, setError] = useState<ApiError | null>(null);
  const [saving, setSaving] = useState(false);

  const destinations = accounts.filter((account) =>
    selected.includes(account.id),
  );
  const needsDate = when === "schedule" && !publishAt;

  /** The value a destination's field shows until it is customized. */
  function inherited(field: TextField): string {
    return field === "title"
      ? contentText(content, "title")
      : common[field].text;
  }

  function discard(accountId: number) {
    setCustomizations((current) => {
      const next = { ...current };
      delete next[accountId];
      return next;
    });
  }

  /** Replaces the selection with the preset's selectable accounts; the preset
   * itself never changes. */
  function applyPreset(preset: DistributionPreset) {
    const next: number[] = [];
    const skipped: string[] = [];
    for (const accountId of preset.account_ids) {
      const account = projectAccounts.find((item) => item.id === accountId);
      if (account === undefined) {
        continue;
      }
      if (!account.is_active) {
        skipped.push(`${accountName(account)} (inactive)`);
      } else if (taken.has(accountId)) {
        skipped.push(
          `${accountName(account)} (already has an active publication)`,
        );
      } else {
        next.push(accountId);
      }
    }
    setSelected(next);
    setExpanded((current) => current.filter((value) => next.includes(value)));
    setCustomizations((current) =>
      Object.fromEntries(
        Object.entries(current).filter(([key]) => next.includes(Number(key))),
      ),
    );
    setPresetNotice({ skipped, empty: next.length === 0 });
  }

  function toggle(accountId: number) {
    if (selected.includes(accountId)) {
      // A destination that is no longer selected sends nothing.
      setSelected((current) => current.filter((value) => value !== accountId));
      setExpanded((current) => current.filter((value) => value !== accountId));
      discard(accountId);
    } else {
      setSelected((current) => [...current, accountId]);
    }
  }

  function toggleExpanded(accountId: number) {
    setExpanded((current) =>
      current.includes(accountId)
        ? current.filter((value) => value !== accountId)
        : [...current, accountId],
    );
  }

  function customize(accountId: number, field: TextField, text: string) {
    setCustomizations((current) => ({
      ...current,
      [accountId]: { ...current[accountId], [field]: { edited: true, text } },
    }));
  }

  function buildBody(): PublicationCreate {
    const body: PublicationCreate = {
      account_ids: destinations.map((account) => account.id),
      ...toOverrides(common),
    };
    const targets: Record<number, PublicationOverrides> = {};
    for (const account of destinations) {
      const customization = customizations[account.id];
      if (isCustomized(customization)) {
        targets[account.id] = toOverrides(customization!);
      }
    }
    if (Object.keys(targets).length > 0) {
      body.targets = targets;
    }
    if (when === "schedule") {
      body.scheduled_at = fromDateTimeLocalValue(publishAt);
    }
    return body;
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaving(true);
    setError(null);
    try {
      onCreated(await createPublications(content.id, buildBody()));
    } catch (caught) {
      const apiError = toApiError(caught);
      setError(apiError);
      // Open the Customize panel of every destination with a field error.
      const withFieldErrors = apiError.fields
        .map((field) => /^targets\.(\d+)\./.exec(field.field)?.[1])
        .filter((value) => value !== undefined)
        .map(Number);
      setExpanded((current) => [...new Set([...current, ...withFieldErrors])]);
      setSaving(false);
    }
  }

  /** Errors about a destination as a whole (inactive, duplicate, not selected). */
  function destinationMessages(accountId: number): string[] {
    return (
      error?.fields
        .filter(
          (field) =>
            field.account_id === accountId ||
            field.field === `targets.${accountId}`,
        )
        .map((field) => field.message) ?? []
    );
  }

  const shownFields = [
    "description_override",
    "hashtags_override",
    "scheduled_at",
    ...destinations.flatMap((account) =>
      textFields(account).map(
        (field) => `targets.${account.id}.${field}_override`,
      ),
    ),
  ];

  return (
    <form aria-label="Distribute" onSubmit={handleSubmit} noValidate>
      <fieldset>
        <legend>Destinations</legend>
        {presets.length > 0 && (
          <>
            <label htmlFor={`${id}-preset`}>Preset</label>
            <select
              id={`${id}-preset`}
              value=""
              disabled={saving}
              onChange={(event) => {
                const preset = presets.find(
                  (item) => item.id === Number(event.target.value),
                );
                if (preset) {
                  applyPreset(preset);
                }
              }}
            >
              <option value="">Choose a preset</option>
              {presets.map((preset) => (
                <option key={preset.id} value={preset.id}>
                  {preset.name}
                </option>
              ))}
            </select>
          </>
        )}
        {presetNotice && presetNotice.skipped.length > 0 && (
          <p className="notice" role="status">
            {presetNotice.skipped.length}{" "}
            {presetNotice.skipped.length === 1
              ? "destination skipped"
              : "destinations skipped"}
            : {presetNotice.skipped.join(", ")}
          </p>
        )}
        {presetNotice?.empty && (
          <p className="muted">No destinations selected from this preset.</p>
        )}
        {accounts.map((account) => {
          const isTaken = taken.has(account.id);
          return (
            <div key={account.id}>
              <label className="checkbox">
                <span>
                  <input
                    type="checkbox"
                    checked={!isTaken && selected.includes(account.id)}
                    disabled={isTaken || saving}
                    onChange={() => toggle(account.id)}
                  />{" "}
                  {accountName(account)}
                  {account.display_name && ` · ${account.display_name}`}
                </span>
                {isTaken && (
                  <span className="muted">
                    Already has an active publication
                  </span>
                )}
              </label>
              {destinationMessages(account.id).map((message) => (
                <p key={message} className="error">
                  {message}
                </p>
              ))}
            </div>
          );
        })}
      </fieldset>
      <PresetManager
        project={project}
        presets={presets}
        selected={destinations.map((account) => account.id)}
        disabled={saving}
        onChange={onPresetsChange}
      />

      <fieldset>
        <legend>Common text</legend>
        {(["description", "hashtags"] as const).map((field) => {
          const inputId = `${id}-common-${field}`;
          const errorField = `${field}_override`;
          const state = common[field];
          const change = (text: string) =>
            setCommon((current) => ({
              ...current,
              [field]: { edited: true, text },
            }));
          return (
            <div key={field} className="metadata-field">
              <label htmlFor={inputId}>{FIELD_LABELS[field]}</label>
              {field === "description" ? (
                <textarea
                  id={inputId}
                  rows={3}
                  value={state.text}
                  onChange={(event) => change(event.target.value)}
                  aria-invalid={
                    error?.fieldMessage(errorField) ? true : undefined
                  }
                />
              ) : (
                <input
                  id={inputId}
                  value={state.text}
                  onChange={(event) => change(event.target.value)}
                  aria-invalid={
                    error?.fieldMessage(errorField) ? true : undefined
                  }
                />
              )}
              <FieldMessage error={error} field={errorField} />
              {state.edited && (
                <div className="actions">
                  <button
                    type="button"
                    onClick={() =>
                      setCommon((current) => ({
                        ...current,
                        [field]: {
                          edited: false,
                          text: contentText(content, field),
                        },
                      }))
                    }
                  >
                    Reset to content value
                  </button>
                </div>
              )}
            </div>
          );
        })}
      </fieldset>

      {destinations.length > 0 && (
        <section aria-label="Selected destinations">
          <h4>Selected destinations</h4>
          {destinations.map((account) => {
            const customization = customizations[account.id];
            const open = expanded.includes(account.id);
            const name = accountName(account);
            return (
              <fieldset key={account.id}>
                <legend>{name}</legend>
                <div className="actions">
                  {isCustomized(customization) && (
                    <span className="badge">Customized</span>
                  )}
                  <button
                    type="button"
                    aria-expanded={open}
                    onClick={() => toggleExpanded(account.id)}
                  >
                    Customize
                  </button>
                  {isCustomized(customization) && (
                    <button type="button" onClick={() => discard(account.id)}>
                      Discard customization
                    </button>
                  )}
                </div>
                {open &&
                  textFields(account).map((field) => {
                    const inputId = `${id}-${account.id}-${field}`;
                    const errorField = `targets.${account.id}.${field}_override`;
                    const state = customization?.[field];
                    const value = state?.edited ? state.text : inherited(field);
                    const change = (text: string) =>
                      customize(account.id, field, text);
                    return (
                      <div key={field} className="metadata-field">
                        <label htmlFor={inputId}>{FIELD_LABELS[field]}</label>
                        {field === "description" ? (
                          <textarea
                            id={inputId}
                            rows={3}
                            value={value}
                            onChange={(event) => change(event.target.value)}
                            aria-invalid={
                              error?.fieldMessage(errorField) ? true : undefined
                            }
                          />
                        ) : (
                          <input
                            id={inputId}
                            value={value}
                            onChange={(event) => change(event.target.value)}
                            aria-invalid={
                              error?.fieldMessage(errorField) ? true : undefined
                            }
                          />
                        )}
                        <FieldMessage error={error} field={errorField} />
                      </div>
                    );
                  })}
              </fieldset>
            );
          })}
        </section>
      )}

      <fieldset>
        <legend>When</legend>
        <label className="checkbox">
          <span>
            <input
              type="radio"
              name={`${id}-when`}
              checked={when === "prepare"}
              onChange={() => setWhen("prepare")}
            />{" "}
            Prepare
          </span>
        </label>
        <label className="checkbox">
          <span>
            <input
              type="radio"
              name={`${id}-when`}
              checked={when === "schedule"}
              onChange={() => setWhen("schedule")}
            />{" "}
            Schedule
          </span>
        </label>
        {when === "schedule" && (
          <>
            <label htmlFor={`${id}-publish-at`}>Date and time</label>
            <input
              id={`${id}-publish-at`}
              type="datetime-local"
              value={publishAt}
              onChange={(event) => setPublishAt(event.target.value)}
              aria-invalid={
                error?.fieldMessage("scheduled_at") ? true : undefined
              }
            />
            <FieldMessage error={error} field="scheduled_at" />
          </>
        )}
      </fieldset>

      <FormError error={error} fields={shownFields} />
      <div className="actions">
        <button
          type="submit"
          disabled={saving || destinations.length === 0 || needsDate}
        >
          Create {destinations.length}{" "}
          {destinations.length === 1 ? "publication" : "publications"}
        </button>
      </div>
      {destinations.length === 0 && (
        <p className="muted">Choose at least one destination.</p>
      )}
      {destinations.length > 0 && needsDate && (
        <p className="muted">Choose a date and time to schedule.</p>
      )}
    </form>
  );
}

/**
 * Save the selection as a preset, rename a preset, replace its destinations with
 * the selection, or delete it. It sits inside the Distribute form, so Enter in
 * its fields never submits the publications.
 */
function PresetManager({
  project,
  presets,
  selected,
  disabled,
  onChange,
}: {
  project: Project;
  presets: DistributionPreset[];
  selected: number[];
  disabled: boolean;
  onChange: (presets: DistributionPreset[]) => void;
}) {
  const id = useId();
  const [name, setName] = useState("");
  const [renaming, setRenaming] = useState<{ id: number; name: string } | null>(
    null,
  );
  // The error and the item it belongs to ("new" or a preset id).
  const [error, setError] = useState<{
    target: "new" | number;
    error: ApiError;
  } | null>(null);
  const [busy, setBusy] = useState(false);

  async function run(target: "new" | number, action: () => Promise<void>) {
    setBusy(true);
    setError(null);
    try {
      await action();
    } catch (caught) {
      setError({ target, error: toApiError(caught) });
    } finally {
      setBusy(false);
    }
  }

  function replace(saved: DistributionPreset) {
    onChange(
      presets.map((preset) => (preset.id === saved.id ? saved : preset)),
    );
  }

  /** New or renamed presets take the backend's order (by name). */
  async function reload() {
    onChange(await listDistributionPresets(project.id));
  }

  const saveNew = () =>
    run("new", async () => {
      await createDistributionPreset(project.id, {
        name,
        account_ids: selected,
      });
      setName("");
      await reload();
    });

  const saveName = () =>
    renaming &&
    run(renaming.id, async () => {
      await updateDistributionPreset(renaming.id, { name: renaming.name });
      setRenaming(null);
      await reload();
    });

  const onEnter = (save: () => unknown) => (event: KeyboardEvent) => {
    if (event.key === "Enter") {
      event.preventDefault();
      void save();
    }
  };

  /** Messages for the item: the name error or one per rejected destination. */
  function messages(target: "new" | number): string[] {
    if (error?.target !== target) {
      return [];
    }
    const fields = error.error.fields.filter((field) =>
      ["name", "account_ids"].includes(field.field),
    );
    return fields.length > 0
      ? fields.map((field) => field.message)
      : [error.error.message];
  }

  const locked = disabled || busy;
  return (
    <details>
      <summary>Manage presets</summary>
      {presets.length > 0 && (
        <ul aria-label="Presets">
          {presets.map((preset) => (
            <li key={preset.id}>
              {renaming?.id === preset.id ? (
                <>
                  <label htmlFor={`${id}-rename-${preset.id}`}>
                    New name for {preset.name}
                  </label>
                  <input
                    id={`${id}-rename-${preset.id}`}
                    value={renaming.name}
                    onChange={(event) =>
                      setRenaming({ id: preset.id, name: event.target.value })
                    }
                    onKeyDown={onEnter(saveName)}
                  />
                  <div className="actions">
                    <button
                      type="button"
                      disabled={locked}
                      onClick={() => void saveName()}
                    >
                      Save name
                    </button>
                    <button type="button" onClick={() => setRenaming(null)}>
                      Cancel
                    </button>
                  </div>
                </>
              ) : (
                <div className="actions">
                  <span>
                    {preset.name}{" "}
                    <span className="muted">
                      {preset.account_ids.length}{" "}
                      {preset.account_ids.length === 1
                        ? "destination"
                        : "destinations"}
                    </span>
                  </span>
                  <button
                    type="button"
                    aria-label={`Rename ${preset.name}`}
                    disabled={locked}
                    onClick={() =>
                      setRenaming({ id: preset.id, name: preset.name })
                    }
                  >
                    Rename
                  </button>
                  <button
                    type="button"
                    aria-label={`Use the selected destinations for ${preset.name}`}
                    disabled={locked || selected.length === 0}
                    onClick={() =>
                      void run(preset.id, async () =>
                        replace(
                          await updateDistributionPreset(preset.id, {
                            account_ids: selected,
                          }),
                        ),
                      )
                    }
                  >
                    Edit destinations
                  </button>
                  <button
                    type="button"
                    aria-label={`Delete ${preset.name}`}
                    disabled={locked}
                    onClick={() => {
                      if (
                        !window.confirm(
                          `Delete the preset "${preset.name}"? Accounts and publications are not affected.`,
                        )
                      ) {
                        return;
                      }
                      void run(preset.id, async () => {
                        await deleteDistributionPreset(preset.id);
                        onChange(
                          presets.filter((item) => item.id !== preset.id),
                        );
                      });
                    }}
                  >
                    Delete
                  </button>
                </div>
              )}
              {messages(preset.id).map((message) => (
                <p key={message} className="error">
                  {message}
                </p>
              ))}
            </li>
          ))}
        </ul>
      )}
      <label htmlFor={`${id}-name`}>Preset name</label>
      <input
        id={`${id}-name`}
        value={name}
        onChange={(event) => setName(event.target.value)}
        onKeyDown={onEnter(
          () => selected.length > 0 && name.trim() && saveNew(),
        )}
      />
      {messages("new").map((message) => (
        <p key={message} className="error">
          {message}
        </p>
      ))}
      <div className="actions">
        <button
          type="button"
          disabled={locked || selected.length === 0 || !name.trim()}
          onClick={() => void saveNew()}
        >
          Save selection as preset
        </button>
      </div>
    </details>
  );
}

/** One compact row per created publication (contracts/ui.md). */
function DistributionResult({
  project,
  created,
  onDistributeAgain,
  onOpenQueue,
}: {
  project: Project;
  created: Publication[];
  onDistributeAgain: () => void;
  onOpenQueue: () => void;
}) {
  const [publications, setPublications] = useState(created);

  const reload = useCallback(async () => {
    try {
      const loaded = await listPublications(project.id);
      setPublications((current) =>
        current.map(
          (publication) =>
            loaded.find((item) => item.id === publication.id) ?? publication,
        ),
      );
    } catch {
      // The rows keep their last known state.
    }
  }, [project.id]);

  return (
    <section aria-label="Distribution result">
      <div className="actions">
        <p role="status">
          Created {publications.length}{" "}
          {publications.length === 1 ? "publication" : "publications"}
        </p>
        <button type="button" onClick={onDistributeAgain}>
          Distribute again
        </button>
        <button type="button" onClick={onOpenQueue}>
          Open queue
        </button>
      </div>
      {publications.map((publication) => (
        <DistributionResultRow
          key={publication.id}
          publication={publication}
          onChanged={reload}
        />
      ))}
    </section>
  );
}

function DistributionResultRow({
  publication: initial,
  onChanged,
}: {
  publication: Publication;
  onChanged: () => Promise<void>;
}) {
  const { publication, setPublication, handleReconciled } = useLivePublication(
    initial,
    onChanged,
  );
  const [check, setCheck] = useState<PublishCheck | null>(null);
  // Bumped after saving options so the publish check is loaded again.
  const [checkVersion, setCheckVersion] = useState(0);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [tiktokMode, setTikTokMode] = useState<TikTokMode | null | undefined>(
    undefined,
  );
  const publishable = isPublishable(publication);
  // Opens when requirements appear and closes once Ready; the user can still
  // open or close it by hand in between.
  const [optionsOpen, setOptionsOpen] = useState(false);

  function handleCheck(next: PublishCheck | null) {
    const hadNeeds = check !== null && !check.eligible;
    const hasNeeds = next !== null && !next.eligible;
    if (hasNeeds !== hadNeeds && next !== null) {
      setOptionsOpen(hasNeeds);
    }
    setCheck(next);
  }

  return (
    <section
      aria-label={accountName(publication.account)}
      className="publication-detail"
    >
      <h4>
        {accountName(publication.account)}{" "}
        <span className={`badge status-${publication.status}`}>
          {publicationStatusLabel(publication)}
        </span>{" "}
        {publishable && check && (
          <span className="muted">
            {check.eligible ? "Ready" : `Needs ${check.problems.length}`}
          </span>
        )}
      </h4>
      {hasPlatformOptions(publication) && (
        <details
          open={optionsOpen}
          onToggle={(event) => setOptionsOpen(event.currentTarget.open)}
        >
          <summary>Platform options</summary>
          <PublicationPlatformOptions
            publication={publication}
            onSaved={() => setCheckVersion((version) => version + 1)}
            onModeChange={setTikTokMode}
          />
        </details>
      )}
      {publishable && (
        <PublishAction
          sendToTikTok={
            isTikTokVideo(publication) && tiktokMode === "INBOX_UPLOAD"
          }
          publication={publication}
          checkVersion={checkVersion}
          dialogOpen={dialogOpen}
          onOpen={() => setDialogOpen(true)}
          onCancel={() => setDialogOpen(false)}
          onPublished={(result) => {
            setDialogOpen(false);
            setPublication(result);
            void onChanged();
          }}
          onReconciled={handleReconciled}
          onCheck={handleCheck}
        />
      )}
      {!PUBLISHING_PLATFORMS.includes(publication.account.platform) && (
        <p className="muted">
          Publishing is not available for this platform yet.
        </p>
      )}
      {publication.status === "scheduled" && (
        <AutoPublishControls
          publication={publication}
          onSaved={(saved) => {
            setPublication(saved);
            void onChanged();
          }}
        />
      )}
    </section>
  );
}

export default Distribute;
