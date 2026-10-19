import { describe, expect, it } from "vitest";
import type { Platform, PublishProblem } from "../../types.ts";
import { platformState } from "./platform-state.ts";

const ACCOUNT = "/p/1/accounts/7";

function check(problems: Partial<PublishProblem>[]) {
  return {
    eligible: problems.length === 0,
    requires_remote_check: false,
    summary: [],
    scheduled_at: null,
    problems: problems.map((problem) => ({
      code: "x",
      message: "Problem.",
      field: null,
      ...problem,
    })),
  };
}

describe("platformState", () => {
  it.each<[string, Platform, Partial<PublishProblem>[], boolean, string]>([
    ["YouTube ready", "youtube", [], false, "Ready"],
    [
      "YouTube details",
      "youtube",
      [
        { code: "youtube_options_incomplete", field: "made_for_kids" },
        {
          code: "youtube_options_incomplete",
          field: "contains_synthetic_media",
        },
      ],
      false,
      "YouTube needs 2 details: Made for kids and Altered or synthetic content.",
    ],
    [
      "TikTok details with a pending declaration",
      "tiktok",
      [
        { code: "tiktok_privacy_required", field: "privacy_level" },
        { code: "tiktok_aigc_required", field: "is_aigc" },
        { code: "tiktok_consent_required" },
      ],
      false,
      "TikTok needs 3 details: Privacy, AI-generated content and declaration.",
    ],
    [
      "TikTok with the declaration accepted locally",
      "tiktok",
      [{ code: "tiktok_consent_required" }],
      true,
      "Ready",
    ],
    [
      "Instagram details",
      "instagram",
      [{ code: "instagram_options_incomplete", field: "is_ai_generated" }],
      false,
      "Instagram needs 1 detail: AI-generated content.",
    ],
  ])("%s", (_label, platform, problems, accepted, summary) => {
    const state = platformState({
      platform,
      check: check(problems),
      declarationAccepted: accepted,
      accountPath: ACCOUNT,
    });
    expect(state.summary).toBe(summary);
    expect(state.state).toBe(summary === "Ready" ? "ready" : "details_needed");
  });

  it.each([
    ["threads_reconnect_required", "Reconnect account"],
    ["reconnect_required", "Reconnect account"],
    ["tiktok_upload_permission_missing", "Reconnect account"],
    ["telegram_channel_required", "Choose a channel"],
    ["account_inactive", "Open account"],
  ])("blocks %s with a link to the account", (code, label) => {
    const state = platformState({
      platform: "threads",
      check: check([
        { code, message: "Fix the account." },
        { code: "threads_alt_text_invalid", field: "alt_text" },
      ]),
      accountPath: ACCOUNT,
    });
    expect(state.state).toBe("blocked");
    expect(state.summary).toBe("Fix the account.");
    expect(state.blockers[0].action).toEqual({ label, to: ACCOUNT });
  });

  it("blocks with the backend message when the card cannot fix it", () => {
    const state = platformState({
      platform: "instagram",
      check: check([
        {
          code: "instagram_caption_invalid",
          field: "caption",
          message: "The caption is too long.",
        },
      ]),
      accountPath: ACCOUNT,
    });
    expect(state).toMatchObject({
      state: "blocked",
      summary: "The caption is too long.",
      blockers: [{ action: null }],
    });
  });

  it("is checking while the publish check loads", () => {
    expect(
      platformState({ platform: "youtube", check: null, accountPath: ACCOUNT })
        .state,
    ).toBe("checking");
  });
});
