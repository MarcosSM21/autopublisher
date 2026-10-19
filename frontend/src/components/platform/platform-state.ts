import {
  platformLabel,
  type Platform,
  type PublishCheck,
} from "../../types.ts";
import { needsSettings, problemText } from "./problem-copy.ts";

/** The human state of one destination's platform details (contracts/ui.md §6). */
export type PlatformReadiness =
  "ready" | "details_needed" | "blocked" | "checking";

export interface PlatformBlocker {
  message: string;
  /** Where the user can fix it, e.g. the account. */
  action: { label: string; to: string } | null;
}

export interface PlatformState {
  state: PlatformReadiness;
  /** One sentence, e.g. "TikTok needs 2 details: Privacy and declaration." */
  summary: string;
  /** What is missing, in the words of the card's fields. */
  details: string[];
  blockers: PlatformBlocker[];
}

interface PlatformStateInput {
  platform: Platform;
  /** The backend publish-check; null while it loads. */
  check: PublishCheck | null;
  /** Whether the local TikTok declaration matches the current options. */
  declarationAccepted?: boolean;
  /** The account's page, for problems fixed there (e.g. reconnect). */
  accountPath: string;
}

/**
 * Card fields named by the backend's `problem.field` (the platform rules stay in
 * the backend: this only says which details are missing, in human words).
 */
const DETAIL_LABELS: Record<string, string> = {
  mode: "How to reach TikTok",
  privacy_level: "Privacy",
  is_aigc: "AI-generated content",
  is_ai_generated: "AI-generated content",
  commercial_disclosure_enabled: "Commercial content",
  made_for_kids: "Made for kids",
  contains_synthetic_media: "Altered or synthetic content",
  alt_text: "Alt text",
};

const DECLARATION = "tiktok_consent_required";

/** Problems fixed in the account, never in the card. */
function connectionAction(code: string): string | null {
  if (
    /(^|_)(reconnect_required|not_connected|permission_missing)$/.test(code)
  ) {
    return "Reconnect account";
  }
  if (code === "telegram_channel_required" || code === "channel_required") {
    return "Choose a channel";
  }
  if (code === "account_inactive" || code === "setup_required") {
    return "Open account";
  }
  return null;
}

function joinLabels(labels: string[]): string {
  return labels.length <= 1
    ? labels.join("")
    : `${labels.slice(0, -1).join(", ")} and ${labels.at(-1)}`;
}

/** Maps the backend problems to Ready / Details needed / Blocked / Checking. */
export function platformState({
  platform,
  check,
  declarationAccepted = false,
  accountPath,
}: PlatformStateInput): PlatformState {
  if (check === null) {
    return {
      state: "checking",
      summary: "Checking…",
      details: [],
      blockers: [],
    };
  }
  const details: string[] = [];
  const blockers: PlatformBlocker[] = [];
  for (const problem of check.problems) {
    if (problem.code === DECLARATION) {
      if (!declarationAccepted && !details.includes("declaration")) {
        details.push("declaration");
      }
      continue;
    }
    const message = problemText(problem.message, problem.code);
    if (needsSettings(problem.message, problem.code)) {
      blockers.push({
        message,
        action: { label: "Open Settings", to: "/settings" },
      });
      continue;
    }
    const action = connectionAction(problem.code);
    if (action !== null) {
      blockers.push({ message, action: { label: action, to: accountPath } });
      continue;
    }
    const label = problem.field ? DETAIL_LABELS[problem.field] : undefined;
    if (label !== undefined) {
      if (!details.includes(label)) {
        details.push(label);
      }
      continue;
    }
    blockers.push({ message, action: null });
  }

  if (blockers.length > 0) {
    return {
      state: "blocked",
      summary: blockers[0].message,
      details,
      blockers,
    };
  }
  if (details.length > 0) {
    const count = `${details.length} ${details.length === 1 ? "detail" : "details"}`;
    return {
      state: "details_needed",
      summary: `${platformLabel(platform)} needs ${count}: ${joinLabels(details)}.`,
      details,
      blockers,
    };
  }
  return { state: "ready", summary: "Ready", details, blockers };
}

export const READINESS_LABELS: Record<PlatformReadiness, string> = {
  ready: "Ready",
  details_needed: "Details needed",
  blocked: "Blocked",
  checking: "Checking",
};

/** The channel a Telegram Post goes to, from the publish check summary. */
export function telegramChannel(check: PublishCheck | null): string | null {
  const channel = check?.summary.find(
    (item) => item.label === "Telegram channel",
  )?.value;
  return channel && channel !== "None" ? channel : null;
}
