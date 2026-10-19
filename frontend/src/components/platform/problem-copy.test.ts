import { describe, expect, it } from "vitest";
import { platformState } from "./platform-state.ts";
import { needsSettings, problemText } from "./problem-copy.ts";

const TELEGRAM =
  "Telegram is not configured. Add your api_id and api_hash to the local Telegram app file (see docs/telegram.md).";
const DELIVERY =
  "Temporary media delivery is not configured. See docs/instagram-publishing.md to set up the storage that lets the platform fetch the media.";

describe("problemText", () => {
  it.each([
    [
      "Telegram by code",
      TELEGRAM,
      "telegram_not_configured",
      "Telegram connection needs setup.",
    ],
    [
      "Telegram by message only (overview detail)",
      TELEGRAM,
      null,
      "Telegram connection needs setup.",
    ],
    [
      "media delivery",
      DELIVERY,
      "media_delivery_not_configured",
      "Media delivery needs setup before media can be published here.",
    ],
    [
      "Threads integration",
      "Threads integration is not configured. See docs/threads-accounts.md.",
      "threads_oauth_not_configured",
      "Threads connection needs setup.",
    ],
    [
      "another message keeps its words, without the docs pointer",
      "The system's secure credential storage is not available. See docs/instagram-accounts.md.",
      "credential_store_unavailable",
      "The system's secure credential storage is not available.",
    ],
    [
      "a user-facing message is untouched",
      "Declare whether it's made for kids.",
      "youtube_options_incomplete",
      "Declare whether it's made for kids.",
    ],
  ])("%s", (_, message, code, expected) => {
    const text = problemText(message, code);
    expect(text).toBe(expected);
    expect(text).not.toMatch(/docs\/|api_id|api_hash|\.md/);
  });

  it("knows which problems are fixed in Settings", () => {
    expect(needsSettings(TELEGRAM)).toBe(true);
    expect(
      needsSettings("Reconnect the account.", "youtube_reconnect_required"),
    ).toBe(false);
  });
});

it("a platform that needs setup is Blocked with human copy and leads to Settings", () => {
  const state = platformState({
    platform: "telegram",
    check: {
      eligible: false,
      requires_remote_check: false,
      summary: [],
      scheduled_at: null,
      problems: [
        { code: "telegram_not_configured", message: TELEGRAM, field: null },
      ],
    },
    accountPath: "/p/1/accounts/7",
  });
  expect(state.state).toBe("blocked");
  expect(state.summary).toBe("Telegram connection needs setup.");
  expect(state.blockers).toEqual([
    {
      message: "Telegram connection needs setup.",
      action: { label: "Open Settings", to: "/settings" },
    },
  ]);
});
