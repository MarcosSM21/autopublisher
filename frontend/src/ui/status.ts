// The single map of product states → visible label, tone and icon
// (contracts/ui.md §5). StatusBadge and any other view read it from here.
import type {
  AccountHealthState,
  PlatformStatus,
  PostDisplayState,
} from "../types.ts";
import type { Tone } from "./Badge.tsx";
import type { IconName } from "./Icon.tsx";

export interface StatusAppearance {
  label: string;
  tone: Tone;
  icon: IconName;
}

export const POST_STATUS: Record<PostDisplayState, StatusAppearance> = {
  draft: { label: "Draft", tone: "neutral", icon: "circle" },
  scheduled_automatic: {
    label: "Scheduled · automatic",
    tone: "info",
    icon: "clock",
  },
  scheduled_manual: {
    label: "Scheduled · manual",
    tone: "neutral",
    icon: "clock",
  },
  scheduled_paused: {
    label: "Scheduled · paused",
    tone: "warning",
    icon: "pause",
  },
  publishing: { label: "Publishing", tone: "info", icon: "clock" },
  published: { label: "Published", tone: "success", icon: "check" },
  failed: { label: "Failed", tone: "danger", icon: "alert" },
  needs_review: { label: "Needs review", tone: "danger", icon: "alert" },
  needs_action: { label: "Needs action", tone: "warning", icon: "alert" },
  missed: { label: "Missed", tone: "danger", icon: "alert" },
  cancelled: { label: "Cancelled", tone: "neutral", icon: "close" },
};

export const ACCOUNT_STATUS: Record<AccountHealthState, StatusAppearance> = {
  ready: { label: "Ready", tone: "success", icon: "check" },
  reconnect_needed: {
    label: "Reconnect needed",
    tone: "danger",
    icon: "alert",
  },
  setup_required: { label: "Finish setup", tone: "warning", icon: "alert" },
  not_connected: { label: "Not connected", tone: "neutral", icon: "circle" },
  inactive: { label: "Inactive", tone: "neutral", icon: "pause" },
};

export const PLATFORM_STATUS: Record<PlatformStatus, StatusAppearance> = {
  configured: { label: "Configured", tone: "success", icon: "check" },
  partial: { label: "Partially configured", tone: "warning", icon: "alert" },
  not_configured: { label: "Not configured", tone: "danger", icon: "alert" },
  coming_soon: { label: "Coming soon", tone: "neutral", icon: "clock" },
};
