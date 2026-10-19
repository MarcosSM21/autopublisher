import { expect, it } from "vitest";
import type { Platform } from "../../types.ts";
import { sentContent } from "./sent-content.ts";
import { attempt, post } from "./test-posts.ts";

function published(platform: Platform, submitted: Record<string, unknown>) {
  return post("published", {
    title: "Current title",
    description: "Current caption",
    account: {
      id: 5,
      platform,
      handle: "a",
      display_name: null,
      is_active: true,
    },
    latest_attempt: attempt({ status: "succeeded", platform, submitted }),
  });
}

it.each([
  [
    "YouTube: title and description sent",
    published("youtube", { title: "Sent title", description: "Sent text" }),
    {
      kind: "sent",
      fields: [
        { label: "Title", value: "Sent title" },
        { label: "Description", value: "Sent text" },
      ],
    },
  ],
  [
    "Instagram: caption and alt text",
    published("instagram", { caption: "Sent caption", alt_text: "Alt" }),
    {
      kind: "sent",
      fields: [
        { label: "Caption", value: "Sent caption" },
        { label: "Alt text", value: "Alt" },
      ],
    },
  ],
  [
    "Threads: text",
    published("threads", { text: "Sent words" }),
    { kind: "sent", fields: [{ label: "Text", value: "Sent words" }] },
  ],
  [
    "TikTok Direct Post: caption",
    published("tiktok", { caption: "Sent tt" }),
    { kind: "sent", fields: [{ label: "Caption", value: "Sent tt" }] },
  ],
  [
    "TikTok Inbox: written in TikTok",
    published("tiktok", { mode: "INBOX_UPLOAD" }),
    { kind: "written_in_tiktok" },
  ],
])("%s", (_, candidate, expected) => {
  expect(sentContent(candidate)).toEqual(expected);
});

it.each([
  [
    "Telegram records only the length",
    published("telegram", { text_length: 12 }),
  ],
  [
    "a legacy post without an attempt",
    post("published", { description: "Current caption" }),
  ],
])("%s → current content, labelled", (_, candidate) => {
  const content = sentContent(candidate);
  expect(content.kind).toBe("current");
  expect(content.kind === "current" && content.fields).toContainEqual({
    label: "Caption",
    value: "Current caption",
  });
});
