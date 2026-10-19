// What a Published Post actually sent (research R-08, plan §17), from the
// non-sensitive snapshot of its last attempt. Platforms that don't record the
// text fall back to the current content, saying it may differ.
import type { Publication } from "../../types.ts";

export interface SentField {
  label: string;
  value: string;
}

export type SentContent =
  /** Recorded in the attempt: exactly what was sent. */
  | { kind: "sent"; fields: SentField[] }
  /** TikTok Upload to Inbox: the caption was written in TikTok. */
  | { kind: "written_in_tiktok" }
  /** Not recorded: the current content, which may differ. */
  | { kind: "current"; fields: SentField[] };

function text(value: unknown): string | null {
  return typeof value === "string" ? value : null;
}

/** The content the Post has now (effective values). */
export function currentFields(post: Publication): SentField[] {
  const fields: SentField[] = [];
  if (post.account.platform === "youtube") {
    fields.push({ label: "Title", value: post.title ?? "" });
  }
  fields.push({
    label: post.content_id === null ? "Text" : "Caption",
    value: post.description ?? "",
  });
  fields.push({
    label: "Hashtags",
    value: post.hashtags.map((tag) => `#${tag}`).join(" "),
  });
  return fields;
}

export function sentContent(post: Publication): SentContent {
  const attempt = post.latest_attempt;
  const submitted = attempt?.submitted ?? {};
  const fallback: SentContent = {
    kind: "current",
    fields: currentFields(post),
  };
  if (attempt === null) {
    return fallback;
  }
  switch (post.account.platform) {
    case "youtube": {
      const title = text(submitted.title);
      const description = text(submitted.description);
      if (title === null && description === null) {
        return fallback;
      }
      return {
        kind: "sent",
        fields: [
          { label: "Title", value: title ?? "" },
          { label: "Description", value: description ?? "" },
        ],
      };
    }
    case "instagram": {
      const caption = text(submitted.caption);
      if (caption === null) {
        return fallback;
      }
      const alt = text(submitted.alt_text);
      return {
        kind: "sent",
        fields: [
          { label: "Caption", value: caption },
          ...(alt ? [{ label: "Alt text", value: alt }] : []),
        ],
      };
    }
    case "threads": {
      const sent = text(submitted.text);
      if (sent === null) {
        return fallback;
      }
      const alt = text(submitted.alt_text);
      return {
        kind: "sent",
        fields: [
          { label: "Text", value: sent },
          ...(alt ? [{ label: "Alt text", value: alt }] : []),
        ],
      };
    }
    case "tiktok": {
      if (
        submitted.mode === "INBOX_UPLOAD" ||
        attempt.details.delivered_to_inbox === true
      ) {
        return { kind: "written_in_tiktok" };
      }
      const caption = text(submitted.caption);
      return caption === null
        ? fallback
        : { kind: "sent", fields: [{ label: "Caption", value: caption }] };
    }
    default:
      // Telegram records only the text length.
      return fallback;
  }
}
