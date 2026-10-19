import { useCallback, useEffect, useRef, useState } from "react";
import type { PublicationUpdate } from "../../../api.ts";
import { useAutosaveRegistry } from "../../../components/platform/autosave-registry.ts";
import type { Publication } from "../../../types.ts";
import Button from "../../../ui/Button.tsx";
import { accountName, toApiError } from "../../../utils.ts";
import { CONTENT_ID, CONTENT_SAVE_KEY } from "../final-action.ts";
import { hashtagsText, usesTitle } from "../snapshot.ts";
import EditContentDialog from "./EditContentDialog.tsx";

interface ContentByDestinationProps {
  drafts: Publication[];
  onSave: (ids: number[], changes: PublicationUpdate) => Promise<void>;
  /** Text posts have no Media to fall back on: their text is always theirs. */
  textPost?: boolean;
}

/** Same values and same provenance: shown together, never called "common". */
function groupKey(post: Publication): string {
  const title = usesTitle(post.account.platform);
  return JSON.stringify([
    title ? post.title : null,
    title ? post.title_override === null : null,
    post.description,
    post.description_override === null,
    post.hashtags,
    post.hashtags_override === null,
  ]);
}

function groups(drafts: Publication[]): Publication[][] {
  const byKey = new Map<string, Publication[]>();
  for (const post of drafts) {
    const key = groupKey(post);
    byKey.set(key, [...(byKey.get(key) ?? []), post]);
  }
  return [...byKey.values()];
}

/**
 * The content each Draft really has (what is saved), grouped only when the
 * value and its provenance are identical. Each field says where it comes
 * from. Edits are explicit (a dialog) and write only the chosen Posts.
 */
function ContentByDestination({
  drafts,
  onSave,
  textPost = false,
}: ContentByDestinationProps) {
  const [editing, setEditing] = useState<Publication | "many" | null>(null);
  const [rowError, setRowError] = useState<{
    id: number;
    message: string;
  } | null>(null);

  // The saves go through the task's registry, so the final action and
  // Finish later wait for them and see a failure.
  const registry = useAutosaveRegistry();
  const register = registry?.register;
  const report = registry?.report;
  const inFlight = useRef<Promise<unknown> | null>(null);
  const failed = useRef(false);
  useEffect(
    () =>
      register?.(CONTENT_SAVE_KEY, async () => {
        while (inFlight.current !== null) {
          await inFlight.current.catch(() => {});
        }
        return !failed.current;
      }),
    [register],
  );
  const setFailed = useCallback(
    (value: boolean) => {
      failed.current = value;
      report?.(CONTENT_SAVE_KEY, value);
    },
    [report],
  );
  const save = useCallback(
    async (ids: number[], changes: PublicationUpdate) => {
      const pending = onSave(ids, changes);
      inFlight.current = pending;
      try {
        await pending;
      } finally {
        inFlight.current = null;
      }
    },
    [onSave],
  );

  async function inheritCaption(post: Publication) {
    setRowError(null);
    try {
      await save([post.id], {
        description_override: null,
        hashtags_override: null,
      });
      setFailed(false);
    } catch (caught) {
      setRowError({ id: post.id, message: toApiError(caught).message });
    }
  }

  return (
    <section
      id={CONTENT_ID}
      tabIndex={-1}
      className="ap-publish-section"
      aria-labelledby="publish-content-title"
    >
      <div className="ap-publish-section__header">
        <h3 id="publish-content-title" className="ap-publish-section__title">
          Content by destination
        </h3>
        {drafts.length > 1 && (
          <Button variant="ghost" onClick={() => setEditing("many")}>
            Edit for these destinations
          </Button>
        )}
      </div>
      <ul className="ap-content-groups">
        {groups(drafts).map((group) => {
          const sample = group[0];
          const title = usesTitle(sample.account.platform);
          return (
            <li
              key={group.map((post) => post.id).join(",")}
              className="ap-content-group"
            >
              <p className="ap-content-group__destinations">
                {group.map((post) => accountName(post.account)).join(", ")}
              </p>
              {title && (
                <p className="ap-content-group__field">
                  <span className="ap-content-group__value">
                    {sample.title || "No title"}
                  </span>
                  <span className="ap-meta">
                    {sample.title_override === null
                      ? "Uses the media's title"
                      : "Custom title"}
                  </span>
                </p>
              )}
              <div className="ap-content-group__field">
                <p className="ap-caption">
                  {sample.description || "No caption"}
                </p>
                <span className="ap-meta">
                  {sample.description_override === null
                    ? "Uses the media's caption"
                    : "Custom text"}
                </span>
              </div>
              <p className="ap-content-group__field">
                <span className="ap-content-group__value">
                  {sample.hashtags.length > 0
                    ? hashtagsText(sample.hashtags)
                    : "No hashtags"}
                </span>
                <span className="ap-meta">
                  {sample.hashtags_override === null
                    ? "Uses the media's hashtags"
                    : "Custom hashtags"}
                </span>
              </p>
              <ul className="ap-content-group__actions">
                {group.map((post) => {
                  const name = accountName(post.account);
                  const custom =
                    !textPost &&
                    (post.description_override !== null ||
                      post.hashtags_override !== null);
                  return (
                    <li key={post.id}>
                      <Button
                        variant="ghost"
                        aria-label={`Customize ${name}`}
                        onClick={() => setEditing(post)}
                      >
                        {/* Several buttons side by side: say which is which. */}
                        {group.length > 1 ? `Customize ${name}` : "Customize"}
                      </Button>
                      {custom && (
                        <Button
                          variant="ghost"
                          aria-label={`Use the media's caption for ${name}`}
                          onClick={() => void inheritCaption(post)}
                        >
                          Use the media's caption
                        </Button>
                      )}
                      {rowError?.id === post.id && (
                        <p className="ap-field__error" role="alert">
                          {rowError.message}
                        </p>
                      )}
                    </li>
                  );
                })}
              </ul>
            </li>
          );
        })}
      </ul>
      {editing !== null && (
        <EditContentDialog
          drafts={drafts}
          single={editing === "many" ? null : editing}
          onClose={() => setEditing(null)}
          onSave={save}
          onFailedChange={setFailed}
        />
      )}
    </section>
  );
}

export default ContentByDestination;
