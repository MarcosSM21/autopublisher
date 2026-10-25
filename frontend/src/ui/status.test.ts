import { describe, expect, it } from "vitest";
import {
  ACCOUNT_STATUS,
  PLATFORM_STATUS,
  POST_STATUS,
  type StatusAppearance,
} from "./status.ts";

// contracts/ui.md §5: labels and icons are unchanged; only tones follow the
// visual refresh (needs_review is warning, publishing active, scheduled neutral).
const EXPECTED: Record<string, StatusAppearance> = {
  draft: { label: "Draft", icon: "circle", tone: "neutral" },
  scheduled_automatic: {
    label: "Scheduled · automatic",
    icon: "clock",
    tone: "neutral",
  },
  scheduled_manual: {
    label: "Scheduled · manual",
    icon: "clock",
    tone: "neutral",
  },
  scheduled_paused: {
    label: "Scheduled · paused",
    icon: "pause",
    tone: "warning",
  },
  publishing: { label: "Publishing", icon: "clock", tone: "active" },
  published: { label: "Published", icon: "check", tone: "success" },
  failed: { label: "Failed", icon: "alert", tone: "danger" },
  needs_review: { label: "Needs review", icon: "alert", tone: "warning" },
  needs_action: { label: "Needs action", icon: "alert", tone: "warning" },
  missed: { label: "Missed", icon: "alert", tone: "danger" },
  cancelled: { label: "Cancelled", icon: "close", tone: "neutral" },
  ready: { label: "Ready", icon: "check", tone: "success" },
  reconnect_needed: {
    label: "Reconnect needed",
    icon: "alert",
    tone: "danger",
  },
  setup_required: { label: "Finish setup", icon: "alert", tone: "warning" },
  not_connected: { label: "Not connected", icon: "circle", tone: "neutral" },
  inactive: { label: "Inactive", icon: "pause", tone: "neutral" },
  configured: { label: "Configured", icon: "check", tone: "success" },
  partial: { label: "Partially configured", icon: "alert", tone: "warning" },
  not_configured: { label: "Not configured", icon: "alert", tone: "danger" },
  coming_soon: { label: "Coming soon", icon: "clock", tone: "neutral" },
};

describe("status map", () => {
  const all = { ...POST_STATUS, ...ACCOUNT_STATUS, ...PLATFORM_STATUS };

  it("covers exactly the documented states", () => {
    expect(Object.keys(all).sort()).toEqual(Object.keys(EXPECTED).sort());
  });

  it.each(Object.entries(EXPECTED))("%s", (state, expected) => {
    expect(all[state as keyof typeof all]).toEqual(expected);
  });
});
