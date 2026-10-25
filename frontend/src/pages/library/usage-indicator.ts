import type { ContentUsage } from "../../types.ts";
import type { Tone } from "../../ui/Badge.tsx";
import type { IconName } from "../../ui/Icon.tsx";
import { formatWhen } from "../../utils.ts";

export type UsageIndicatorKind =
  "attention" | "upcoming" | "drafts" | "published" | "unused";

export interface UsageIndicator {
  kind: UsageIndicatorKind;
  label: string;
  tone: Tone;
  icon: IconName;
}

function plural(count: number, one: string, many: string): string {
  return `${count} ${count === 1 ? one : many}`;
}

/** Whether a Media has no Post left except cancelled ones. */
export function isNotUsedYet(usage: ContentUsage): boolean {
  return usage.publication_count === usage.cancelled_count;
}

/**
 * The one usage indicator of a Media card, by priority (data-model §1): needs
 * attention > scheduled or publishing > drafts > published > not used yet.
 * The counts come from the backend's display states; nothing is recomputed.
 */
export function usageIndicator(
  usage: ContentUsage,
  now: Date = new Date(),
): UsageIndicator | null {
  if (usage.attention_count > 0) {
    return {
      kind: "attention",
      label: `${usage.attention_count} ${usage.attention_count === 1 ? "needs" : "need"} attention`,
      tone: "warning",
      icon: "alert",
    };
  }
  if (usage.upcoming_count > 0) {
    return {
      kind: "upcoming",
      label: usage.next_scheduled_at
        ? `Scheduled · ${formatWhen(usage.next_scheduled_at, now)}`
        : "Publishing",
      // Same tones as the status map: scheduled is neutral, publishing active.
      tone: usage.next_scheduled_at ? "neutral" : "active",
      icon: "clock",
    };
  }
  if (usage.draft_count > 0) {
    return {
      kind: "drafts",
      label: plural(usage.draft_count, "draft", "drafts"),
      tone: "neutral",
      icon: "circle",
    };
  }
  if (usage.published_count > 0) {
    return {
      kind: "published",
      label: "Published",
      tone: "success",
      icon: "check",
    };
  }
  if (isNotUsedYet(usage)) {
    return {
      kind: "unused",
      label: "Not used yet",
      tone: "neutral",
      icon: "circle",
    };
  }
  return null;
}
