import { describe, expect, it } from "vitest";
import type {
  AccountHealth,
  AssetPublication,
  MediaType,
  Platform,
  PlatformAvailability,
  PostDisplayState,
} from "../../types.ts";
import { destinations, presetSelection } from "./destinations.ts";

const CAPS: Record<string, AccountHealth["capabilities"]> = {
  youtube: ["videos"],
  instagram: ["images", "videos"],
  telegram: ["images", "videos"],
  threads: ["text", "images", "videos"],
};

function account(
  id: number,
  platform: Platform,
  values: Partial<AccountHealth> = {},
): AccountHealth {
  return {
    account_id: id,
    platform,
    label: `${platform} @a${id}`,
    display_name: null,
    is_active: true,
    state: "ready",
    identity: null,
    expires_at: null,
    expiring: false,
    capabilities: CAPS[platform] ?? [],
    issue: null,
    can_discard: false,
    ...values,
  };
}

function row(
  accountId: number,
  publicationId: number,
  state: PostDisplayState,
): AssetPublication {
  return {
    publication_id: publicationId,
    account_id: accountId,
    display_state: state,
  } as AssetPublication;
}

function availability(
  platform: Platform,
  values: Partial<PlatformAvailability>,
): PlatformAvailability {
  return {
    platform,
    label: platform,
    integration_available: true,
    status: "configured",
    can_connect: true,
    missing: [],
    message: null,
    ...values,
  };
}

function only(
  health: AccountHealth,
  {
    mediaType = "video" as MediaType,
    usage = [] as AssetPublication[],
    platforms = [] as PlatformAvailability[],
    setIds = [] as number[],
  } = {},
) {
  return destinations({
    projectId: 1,
    mode: "media",
    mediaType,
    health: [health],
    platforms,
    usage,
    setIds,
  })[0];
}

describe("destination reasons", () => {
  it.each([
    [
      "an image on YouTube",
      only(account(1, "youtube"), { mediaType: "image" }),
      "Video only",
      null,
    ],
    [
      "a platform coming soon",
      only(account(1, "telegram"), {
        platforms: [
          availability("telegram", {
            status: "coming_soon",
            integration_available: false,
          }),
        ],
      }),
      "Coming soon",
      null,
    ],
    [
      "missing media delivery",
      only(account(1, "instagram"), {
        platforms: [
          availability("instagram", {
            status: "partial",
            missing: ["media_delivery"],
          }),
        ],
      }),
      "Configure in Settings",
      "/settings",
    ],
    [
      "an account to reconnect",
      only(account(1, "youtube", { state: "reconnect_needed" })),
      "Reconnect account",
      "/p/1/accounts/1",
    ],
    [
      "an account to finish",
      only(account(1, "youtube", { state: "setup_required" })),
      "Finish account setup",
      "/p/1/accounts/1",
    ],
    [
      "Telegram without channel",
      only(
        account(1, "telegram", {
          state: "setup_required",
          issue: { code: "channel_required", message: "Choose" },
        }),
      ),
      "Choose a channel",
      "/p/1/accounts/1",
    ],
    [
      "a scheduled post of this Media",
      only(account(1, "youtube"), {
        usage: [row(1, 40, "scheduled_automatic")],
      }),
      "Already scheduled",
      "/p/1/posts/40",
    ],
    [
      "a post publishing now",
      only(account(1, "youtube"), { usage: [row(1, 41, "publishing")] }),
      "Publishing now",
      "/p/1/posts/41",
    ],
    [
      "a failed post",
      only(account(1, "youtube"), { usage: [row(1, 42, "failed")] }),
      "Has a failed post",
      "/p/1/posts/42",
    ],
  ])("%s → %s", (_, destination, reason, to) => {
    expect(destination.status).toEqual({
      kind: "blocked",
      reason,
      action: to === null ? null : expect.objectContaining({ to }),
    });
  });

  it("published and cancelled posts don't block; a Draft outside the set offers Add to this task", () => {
    expect(
      only(account(1, "youtube"), {
        usage: [row(1, 50, "published"), row(1, 51, "cancelled")],
      }).status,
    ).toEqual({ kind: "available" });
    expect(
      only(account(1, "youtube"), { usage: [row(1, 52, "draft")] }).status,
    ).toEqual({ kind: "has_draft", postId: 52 });
    expect(
      only(account(1, "youtube"), {
        usage: [row(1, 52, "draft")],
        setIds: [52],
      }).status,
    ).toEqual({ kind: "member", postId: 52 });
  });

  it("hides inactive accounts and lists available ones first", () => {
    const list = destinations({
      projectId: 1,
      mode: "media",
      mediaType: "image",
      health: [
        account(1, "youtube"),
        account(2, "telegram", { is_active: false, state: "inactive" }),
        account(3, "instagram"),
      ],
      platforms: [],
      usage: [],
      setIds: [],
    });
    expect(list.map((item) => item.accountId)).toEqual([3, 1]);
  });

  it("a known cancellation outranks the usage loaded at mount", () => {
    const list = destinations({
      projectId: 1,
      mode: "media",
      mediaType: "video",
      health: [account(1, "youtube")],
      platforms: [],
      usage: [row(1, 60, "draft")],
      setIds: [],
      known: new Map([[60, "cancelled"]]),
    });
    expect(list[0].status).toEqual({ kind: "available" });
  });
});

it("a preset replaces the selection with its usable destinations and skips the rest", () => {
  const health = [
    account(1, "telegram"),
    account(2, "youtube"),
    account(3, "instagram", { is_active: false, state: "inactive" }),
  ];
  const list = destinations({
    projectId: 1,
    mode: "media",
    mediaType: "image",
    health,
    platforms: [],
    usage: [],
    setIds: [],
  });
  expect(presetSelection([3, 2, 1], list, health)).toEqual({
    selected: [1],
    skipped: [
      { accountId: 3, name: "instagram @a3", reason: "Inactive" },
      { accountId: 2, name: "youtube @a2", reason: "Video only" },
    ],
  });
});
