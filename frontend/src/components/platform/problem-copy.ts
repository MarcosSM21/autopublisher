/**
 * Human copy for the few backend problems whose message is written for whoever
 * configures the app (local files, docs, api_id/api_hash), not for the person
 * publishing. Only these known cases are rewritten; every other message is the
 * backend's own, already written for the user. Some sources carry only the
 * message (the overview's detail), so a case matches by code or by the start of
 * its message.
 */
interface KnownProblem {
  codes: readonly string[];
  /** How the backend's message starts (its constant text). */
  starts: string;
  text: string;
}

const SETUP: KnownProblem[] = [
  {
    codes: ["telegram_not_configured"],
    starts: "Telegram is not configured.",
    text: "Telegram connection needs setup.",
  },
  {
    codes: ["media_delivery_not_configured"],
    starts: "Temporary media delivery is not configured.",
    text: "Media delivery needs setup before media can be published here.",
  },
  {
    codes: ["instagram_oauth_not_configured"],
    starts: "Instagram integration is not configured.",
    text: "Instagram connection needs setup.",
  },
  {
    codes: ["threads_oauth_not_configured"],
    starts: "Threads integration is not configured.",
    text: "Threads connection needs setup.",
  },
  {
    codes: ["tiktok_oauth_not_configured"],
    starts: "TikTok integration is not configured.",
    text: "TikTok connection needs setup.",
  },
];

/** "… See docs/x.md." or "… (see docs/x.md)": a pointer for the app's admin. */
const DOCS_HINT = /\s*(\(see docs\/[^)]*\)|See docs\/\S+?\.md[^.]*\.)/gi;

function known(code: string | null, message: string): KnownProblem | null {
  return (
    SETUP.find(
      (item) =>
        (code !== null && item.codes.includes(code)) ||
        message.startsWith(item.starts),
    ) ?? null
  );
}

/** The message to show for a backend problem, without setup internals. */
export function problemText(
  message: string,
  code: string | null = null,
): string {
  const match = known(code, message);
  if (match !== null) {
    return match.text;
  }
  return message
    .replace(DOCS_HINT, "")
    .replace(/\.{2,}$/, ".")
    .trim();
}

/** Problems fixed in Settings (the app's platform setup), not in the account. */
export function needsSettings(message: string, code: string | null = null) {
  return known(code, message) !== null;
}
