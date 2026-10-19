// Which accounts a Publish task can send to, and why the others can't (spec
// FR-021/FR-022, FR-035). Pure: derived from account health, platform
// availability, the publisher capabilities, the media type and the Posts the
// Media already has. The backend still decides on create.
import type {
  AccountHealth,
  AssetPublication,
  MediaType,
  Platform,
  PlatformAvailability,
  PostDisplayState,
} from "../../types.ts";
import type { PublishMode } from "./publish-set.ts";

export type DestinationStatus =
  | { kind: "available" }
  /** Already a Post of this task. */
  | { kind: "member"; postId: number }
  /** An active Draft of this Media outside the task: `Add to this task`. */
  | { kind: "has_draft"; postId: number }
  | {
      kind: "blocked";
      reason: string;
      action: { label: string; to: string } | null;
    };

export interface Destination {
  accountId: number;
  platform: Platform;
  /** e.g. "YouTube @chan" (the backend's account label). */
  name: string;
  status: DestinationStatus;
}

interface DestinationsInput {
  projectId: number;
  mode: PublishMode;
  /** The Media's type (media mode). */
  mediaType: MediaType | null;
  health: readonly AccountHealth[];
  platforms: readonly PlatformAvailability[];
  /** The Media's Posts (GET /contents/{id}/usage), as loaded. */
  usage: readonly AssetPublication[];
  /** Ids in `?posts=`. */
  setIds: readonly number[];
  /**
   * What this task knows better than the usage loaded at mount: current
   * states of its members and the Posts it cancelled.
   */
  known?: ReadonlyMap<number, PostDisplayState>;
}

/** Display states that no longer block a new Post (history). */
const HISTORY: PostDisplayState[] = ["published", "cancelled"];

const ACTIVE_REASONS: Partial<Record<PostDisplayState, string>> = {
  scheduled_automatic: "Already scheduled",
  scheduled_manual: "Already scheduled",
  scheduled_paused: "Already scheduled",
  publishing: "Publishing now",
  failed: "Has a failed post",
  needs_review: "Has a post that needs review",
  needs_action: "Waiting in TikTok",
  missed: "Has a missed post",
};

function mediaReason(
  mode: PublishMode,
  mediaType: MediaType | null,
  health: AccountHealth,
): string | null {
  const caps = health.capabilities;
  if (mode === "text") {
    return caps.includes("text") ? null : "Needs media";
  }
  if (mediaType === "video" && !caps.includes("videos")) {
    return caps.includes("images") ? "Images only" : "Not available for videos";
  }
  if (mediaType === "image" && !caps.includes("images")) {
    return caps.includes("videos") ? "Video only" : "Not available for images";
  }
  return null;
}

function platformReason(
  mode: PublishMode,
  availability: PlatformAvailability | undefined,
): DestinationStatus | null {
  if (availability === undefined) {
    return null;
  }
  if (
    availability.status === "coming_soon" ||
    !availability.integration_available
  ) {
    return { kind: "blocked", reason: "Coming soon", action: null };
  }
  if (
    availability.status === "not_configured" ||
    (mode === "media" && availability.missing.includes("media_delivery"))
  ) {
    return {
      kind: "blocked",
      reason: "Configure in Settings",
      action: { label: "Open Settings", to: "/settings" },
    };
  }
  return null;
}

function healthReason(
  health: AccountHealth,
  accountPath: string,
): DestinationStatus | null {
  const open = (label: string): DestinationStatus => ({
    kind: "blocked",
    reason: label,
    action: { label: "Open account", to: accountPath },
  });
  switch (health.state) {
    case "ready":
      return null;
    case "reconnect_needed":
      return open("Reconnect account");
    case "setup_required":
      return open(
        health.issue?.code === "channel_required"
          ? "Choose a channel"
          : "Finish account setup",
      );
    case "not_connected":
      return open("Connect account");
    case "inactive":
      return open("Reactivate account");
  }
}

/** The account's active (non-history) Post of this Media, if any. */
function activePost(
  accountId: number,
  usage: readonly AssetPublication[],
  known: ReadonlyMap<number, PostDisplayState> | undefined,
): { id: number; state: PostDisplayState } | null {
  for (const row of usage) {
    if (row.account_id !== accountId) {
      continue;
    }
    const state = known?.get(row.publication_id) ?? row.display_state;
    if (!HISTORY.includes(state)) {
      return { id: row.publication_id, state };
    }
  }
  return null;
}

/**
 * Every active account of the project as a destination: the ones that can be
 * chosen first, then the others with their reason. Inactive accounts are left
 * out. Order within each group follows the account health list.
 */
export function destinations({
  projectId,
  mode,
  mediaType,
  health,
  platforms,
  usage,
  setIds,
  known,
}: DestinationsInput): Destination[] {
  const list = health
    .filter((account) => account.is_active && account.state !== "inactive")
    .map((account): Destination => {
      const accountPath = `/p/${projectId}/accounts/${account.account_id}`;
      const status = ((): DestinationStatus => {
        const media = mediaReason(mode, mediaType, account);
        if (media !== null) {
          return { kind: "blocked", reason: media, action: null };
        }
        const platform = platformReason(
          mode,
          platforms.find((item) => item.platform === account.platform),
        );
        if (platform !== null) {
          return platform;
        }
        const post =
          mode === "media"
            ? activePost(account.account_id, usage, known)
            : null;
        if (post !== null) {
          if (setIds.includes(post.id)) {
            return { kind: "member", postId: post.id };
          }
          if (post.state === "draft") {
            return { kind: "has_draft", postId: post.id };
          }
          return {
            kind: "blocked",
            reason: ACTIVE_REASONS[post.state] ?? "Has an active post",
            action: {
              label: "View post",
              to: `/p/${projectId}/posts/${post.id}`,
            },
          };
        }
        return healthReason(account, accountPath) ?? { kind: "available" };
      })();
      return {
        accountId: account.account_id,
        platform: account.platform,
        name: account.label,
        status,
      };
    });
  const blocked = (destination: Destination) =>
    destination.status.kind === "blocked" ? 1 : 0;
  return [...list].sort((a, b) => blocked(a) - blocked(b));
}

/**
 * Applying a preset replaces the selection with its usable destinations; the
 * others are skipped with their reason. The preset itself never changes.
 */
export function presetSelection(
  accountIds: readonly number[],
  list: readonly Destination[],
  health: readonly AccountHealth[],
): {
  selected: number[];
  skipped: { accountId: number; name: string; reason: string }[];
} {
  const selected: number[] = [];
  const skipped: { accountId: number; name: string; reason: string }[] = [];
  for (const accountId of accountIds) {
    const destination = list.find((item) => item.accountId === accountId);
    if (destination === undefined) {
      const account = health.find((item) => item.account_id === accountId);
      if (account !== undefined) {
        skipped.push({ accountId, name: account.label, reason: "Inactive" });
      }
      continue;
    }
    switch (destination.status.kind) {
      case "available":
        selected.push(accountId);
        break;
      case "has_draft":
        skipped.push({
          accountId,
          name: destination.name,
          reason: "Has a draft",
        });
        break;
      case "member":
        skipped.push({
          accountId,
          name: destination.name,
          reason: "Already in this task",
        });
        break;
      case "blocked":
        skipped.push({
          accountId,
          name: destination.name,
          reason: destination.status.reason,
        });
        break;
    }
  }
  // Destination-list order, like a manual selection.
  const order = list.map((item) => item.accountId);
  selected.sort((a, b) => order.indexOf(a) - order.indexOf(b));
  return { selected, skipped };
}
