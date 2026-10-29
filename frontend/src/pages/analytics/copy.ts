import type {
  CapabilityState,
  ContentTypeSummary,
  MetricRefreshStatus,
  PublicationAnalyticsRead,
} from "../../types.ts";
import type { Tone } from "../../ui/Badge.tsx";
import type { IconName } from "../../ui/Icon.tsx";

export const NUMBER = new Intl.NumberFormat();
export const PERCENT = new Intl.NumberFormat(undefined, {
  style: "percent",
  maximumFractionDigits: 2,
});

/** Common labels of the catalog concepts (alignment only, never a comparison). */
export const CONCEPT_LABELS: Record<string, string> = {
  views: "Views",
  likes: "Likes",
  comments: "Comments",
  shares: "Shares",
};

export const CONTENT_TYPE_LABELS: Record<
  ContentTypeSummary["content_type"],
  string
> = { image: "Image", video: "Video", text: "Text" };

/** Why a post has no remote link (the backend's `not_linked_reason`). */
export const NOT_LINKED_REASONS: Record<string, string> = {
  remote_id_missing: "AutoPublisher has no remote id for this post.",
  remote_identity_unavailable:
    "The platform didn't confirm this post's id, so its metrics can't be read.",
  remote_identity_changed:
    "Published by another account than the one connected now, so its metrics can't be read.",
  inbox_upload:
    "Sent to the TikTok inbox: there is no public post to read metrics from.",
  no_succeeded_attempt: "This post has no successful publication to read.",
  not_published: "Only published posts have metrics.",
};

export function notLinkedText(reason: string | null): string {
  return (
    (reason && NOT_LINKED_REASONS[reason]) ??
    "AutoPublisher has no remote link for this post."
  );
}

interface Appearance {
  label: string;
  tone: Tone;
  icon?: IconName;
}

/** Account capability, as a short state and a sentence. */
export const CAPABILITY: Record<
  CapabilityState,
  Appearance & { description: string }
> = {
  supported: {
    label: "Metrics available",
    tone: "success",
    icon: "check",
    description: "AutoPublisher reads this account's metrics.",
  },
  permission_required: {
    label: "Permission needed",
    tone: "warning",
    icon: "alert",
    description:
      "These metrics need a permission AutoPublisher doesn't request yet.",
  },
  not_supported: {
    label: "Not supported yet",
    tone: "neutral",
    description:
      "AutoPublisher doesn't read this platform's metrics in this version.",
  },
  not_available_on_platform: {
    label: "Not available",
    tone: "neutral",
    description: "This platform offers no metrics for these posts.",
  },
  not_applicable: {
    label: "Not applicable",
    tone: "neutral",
    description: "AutoPublisher doesn't publish to this platform.",
  },
  not_connected: {
    label: "Not connected",
    tone: "neutral",
    description: "Connect this account to read its metrics.",
  },
  reconnect_required: {
    label: "Reconnect needed",
    tone: "danger",
    icon: "alert",
    description: "Reconnect this account to read its metrics again.",
  },
};

/** Refresh state of one post. */
export const REFRESH: Record<
  MetricRefreshStatus,
  Appearance & { failure?: string }
> = {
  ok: { label: "Up to date", tone: "success", icon: "check" },
  pending: { label: "Updating", tone: "active", icon: "clock" },
  stale: {
    label: "Out of date",
    tone: "warning",
    icon: "alert",
    failure: "AutoPublisher will try again later.",
  },
  rate_limited: {
    label: "Paused by the platform",
    tone: "warning",
    icon: "pause",
    failure: "The platform limited requests. AutoPublisher will try later.",
  },
  reconnect_required: {
    label: "Reconnect needed",
    tone: "danger",
    icon: "alert",
    failure: "Reconnect the account to update these metrics.",
  },
  permission_required: {
    label: "Permission needed",
    tone: "warning",
    icon: "alert",
    failure: "The account lacks the permission to read these metrics.",
  },
  remote_not_found: {
    label: "Not found yet",
    tone: "warning",
    icon: "alert",
    failure:
      "The post wasn't found on the platform. AutoPublisher will check again before marking it deleted.",
  },
  remote_deleted: {
    label: "Deleted on the platform",
    tone: "neutral",
    failure: "The post no longer exists on the platform.",
  },
};

export function ageText(days: number): string {
  if (days === 0) return "Published today";
  if (days === 1) return "Published 1 day ago";
  return `Published ${days} days ago`;
}

export function daysText(days: number): string {
  return days === 1 ? "1 day" : `${days} days`;
}

/** Why a post shows no metrics: its account's capability, then its link. */
export function whyNoMetrics(row: PublicationAnalyticsRead): string | null {
  if (row.capability_state !== "supported") {
    return CAPABILITY[row.capability_state].description;
  }
  if (row.link_state === "not_linked") {
    return notLinkedText(row.not_linked_reason);
  }
  return null;
}
