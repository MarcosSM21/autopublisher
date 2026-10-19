// The final action of a Publish task (contracts/api.md §5, plan §9–§10):
// validate every Draft before anything is written, then run each Post on its
// own, in set order, with the existing endpoints. No batch, no rollback.
import {
  confirmTikTokConsent,
  getPublication,
  getPublishCheck,
  getTikTokOptions,
  publishNow,
  updatePublication,
} from "../../api.ts";
import type { AutosaveRegistryValue } from "../../components/platform/autosave-registry.ts";
import { platformState } from "../../components/platform/platform-state.ts";
import {
  isDeclarationAccepted,
  type DeclarationAcceptance,
} from "../../components/platform/tiktok-declaration.ts";
import type { Publication } from "../../types.ts";
import {
  accountName,
  fromDateTimeLocalValue,
  isFuture,
  toApiError,
} from "../../utils.ts";
import { problemText } from "../../components/platform/problem-copy.ts";

export type RunKind = "now" | "schedule";

/** The single primary CTA of Review (N = Drafts in review). */
export function ctaLabel(run: RunKind, count: number): string {
  return run === "now"
    ? `Publish to ${count} ${count === 1 ? "destination" : "destinations"}`
    : `Schedule ${count} ${count === 1 ? "post" : "posts"}`;
}

/** One problem of the error summary: its text and the element it leads to. */
export interface SummaryItem {
  target: string;
  text: string;
}

/** Ids the summary links to (cards, fields). */
export const WHEN_DATE_ID = "publish-when-date";
export const CONTENT_ID = "publish-content";
export const TEXT_ID = "publish-text";
export const DESTINATIONS_ID = "publish-destinations";
export const CONTENT_SAVE_KEY = "content-by-destination";

export function destinationRowId(accountId: number): string {
  return `publish-destination-${accountId}`;
}

export function customFieldId(accountId: number, field: string): string {
  return `publish-custom-${accountId}-${field}`;
}

export function cardId(postId: number): string {
  return `publish-platform-${postId}`;
}

export function declarationId(postId: number): string {
  return `${cardId(postId)}-declaration`;
}

interface PrevalidationInput {
  drafts: readonly Publication[];
  declarations: Readonly<Record<number, DeclarationAcceptance | null>>;
  run: RunKind;
  /** The datetime-local value of Schedule. */
  at: string;
  registry: Pick<AutosaveRegistryValue, "flushAll" | "failedKeys">;
}

export interface Prevalidation {
  items: SummaryItem[];
  /** The declaration to record before each TikTok Direct Post. */
  consents: Map<number, DeclarationAcceptance>;
}

/**
 * Everything before the first write (plan §10, "validation failure"): pending
 * saves flushed, no failed save, every Draft ready by its publish check, the
 * TikTok declaration accepted for the options on screen, and a future date.
 * Only reads: if any item is returned, nothing is started.
 */
export async function prevalidate({
  drafts,
  declarations,
  run,
  at,
  registry,
}: PrevalidationInput): Promise<Prevalidation> {
  const items: SummaryItem[] = [];
  const consents = new Map<number, DeclarationAcceptance>();
  const flushed = await registry.flushAll();
  const failed = registry.failedKeys();
  for (const key of failed) {
    const match = /^post-(\d+)$/.exec(key);
    const post = match
      ? drafts.find((draft) => draft.id === Number(match[1]))
      : undefined;
    if (post) {
      items.push({
        target: cardId(post.id),
        text: `${accountName(post.account)}: a change couldn't be saved. Retry it.`,
      });
    } else if (key === CONTENT_SAVE_KEY) {
      items.push({
        target: CONTENT_ID,
        text: "A content change couldn't be saved. Retry it.",
      });
    }
  }
  if (!flushed && items.length === 0) {
    items.push({
      target: CONTENT_ID,
      text: "Some changes couldn't be saved. Retry them.",
    });
  }

  const checks = await Promise.all(
    drafts.map(async (post) => {
      try {
        const [check, options] = await Promise.all([
          getPublishCheck(post.id),
          post.account.platform === "tiktok"
            ? getTikTokOptions(post.id)
            : Promise.resolve(null),
        ]);
        return { post, check, options, error: null };
      } catch (caught) {
        return {
          post,
          check: null,
          options: null,
          error: problemText(toApiError(caught).message),
        };
      }
    }),
  );
  for (const { post, check, options, error } of checks) {
    const name = accountName(post.account);
    if (error !== null || check === null) {
      items.push({
        target: cardId(post.id),
        text: `${name}: couldn't check this destination (${error}).`,
      });
      continue;
    }
    // Without the declaration: what else is missing (fields, blockers).
    const state = platformState({
      platform: post.account.platform,
      check,
      declarationAccepted: true,
      accountPath: `/p/${post.project_id}/accounts/${post.account_id}`,
    });
    if (state.state !== "ready") {
      items.push({
        target: cardId(post.id),
        text: `${name}: ${state.summary}`,
      });
    }
    if (options?.mode === "DIRECT_POST") {
      const accepted = declarations[post.id] ?? null;
      if (isDeclarationAccepted(accepted, options)) {
        consents.set(post.id, accepted!);
      } else {
        items.push({
          target: declarationId(post.id),
          text: `${name}: TikTok declaration`,
        });
      }
    }
  }

  if (run === "schedule") {
    if (!at) {
      items.push({ target: WHEN_DATE_ID, text: "Choose a date and time." });
    } else if (!isFuture(fromDateTimeLocalValue(at))) {
      items.push({
        target: WHEN_DATE_ID,
        text: "Choose a date and time in the future.",
      });
    }
  }
  return { items, consents };
}

export interface RunEvent {
  id: number;
  /** The Post after its step (or as reloaded after a failure). */
  post: Publication | null;
  /** Why this Post didn't start or wasn't scheduled. */
  error: string | null;
  /** The options changed after the check: the declaration must be redone. */
  staleConsent: boolean;
}

interface RunInput {
  ids: readonly number[];
  consents: ReadonlyMap<number, DeclarationAcceptance>;
  run: RunKind;
  /** ISO instant (Schedule). */
  scheduledAt: string | null;
  onEvent: (event: RunEvent) => void;
}

/**
 * Starts (or schedules) each Post in order. A failure stops only that Post;
 * the others continue. It is a plain async loop: nothing cancels it when the
 * page unmounts (SPA navigation), so every start is still sent. The caller
 * decides whether to apply events (it stops updating an unmounted page).
 */
export async function runSet({
  ids,
  consents,
  run,
  scheduledAt,
  onEvent,
}: RunInput): Promise<void> {
  for (const id of ids) {
    try {
      const consent = consents.get(id);
      if (consent) {
        await confirmTikTokConsent(id, consent.fingerprint, consent.version);
      }
      const post =
        run === "now"
          ? await publishNow(id, false)
          : await updatePublication(id, {
              scheduled_at: scheduledAt,
              auto_publish_enabled: true,
            });
      onEvent({ id, post, error: null, staleConsent: false });
    } catch (caught) {
      const error = toApiError(caught);
      const stale = error.code === "tiktok_consent_stale";
      // The Post stays in its real state: read it again (read-only).
      const post = await getPublication(id).catch(() => null);
      onEvent({
        id,
        post,
        error: stale
          ? "Confirm the TikTok declaration again."
          : problemText(error.message, error.code),
        staleConsent: stale,
      });
    }
  }
}
