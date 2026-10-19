import { expect, it } from "vitest";
import { buildCreateBody, commonFromMedia } from "./snapshot.ts";

const media = { title: "Summer teaser" };
const common = { description: "Media caption", hashtags: "#summer #clip" };
const youtube = { accountId: 3, platform: "youtube" as const };
const telegram = { accountId: 7, platform: "telegram" as const };

it.each([
  [
    "explicit values with no edits",
    {},
    {
      3: {
        description_override: "Media caption",
        hashtags_override: ["#summer", "#clip"],
        title_override: "Summer teaser",
      },
      7: {
        description_override: "Media caption",
        hashtags_override: ["#summer", "#clip"],
      },
    },
  ],
  [
    "a customization wins over the common text",
    { 7: { description: "Only for Telegram" } },
    {
      3: {
        description_override: "Media caption",
        hashtags_override: ["#summer", "#clip"],
        title_override: "Summer teaser",
      },
      7: {
        description_override: "Only for Telegram",
        hashtags_override: ["#summer", "#clip"],
      },
    },
  ],
  [
    "explicit empty values stay explicit",
    { 3: { title: "", description: "", hashtags: "" } },
    {
      3: {
        description_override: "",
        hashtags_override: [],
        title_override: "",
      },
      7: {
        description_override: "Media caption",
        hashtags_override: ["#summer", "#clip"],
      },
    },
  ],
])("%s", (_, custom, targets) => {
  const body = buildCreateBody([youtube, telegram], common, custom, media);
  expect(body).toEqual({ account_ids: [3, 7], targets });
  // No common fields, no date, no auto-publish.
  expect(Object.keys(body).sort()).toEqual(["account_ids", "targets"]);
});

it("only YouTube gets a title, empty when the Media has none", () => {
  const body = buildCreateBody(
    [youtube, telegram],
    common,
    {},
    { title: null },
  );
  expect(body.targets?.[3].title_override).toBe("");
  expect(body.targets?.[7]).not.toHaveProperty("title_override");
});

it("prefills the common text from the Media", () => {
  expect(
    commonFromMedia({ description: null, hashtags: ["a", "b"] } as never),
  ).toEqual({ description: "", hashtags: "#a #b" });
});
