import { cleanup, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { FakeApi } from "../../test-fake-api.ts";
import { renderRoute } from "../../test-utils.tsx";
import { setHealth, setViewport } from "../publish/test-publish.ts";
import { attemptEvents } from "./activity-events.ts";
import { attempt } from "./test-posts.ts";

let api: FakeApi;

beforeEach(() => {
  api = new FakeApi();
  api.install();
  setViewport(1280);
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

it.each([
  [
    attempt({
      trigger: "scheduled",
      status: "failed",
      error: {
        code: "ig_bad_format",
        message: "Instagram rejected the video format",
      },
      platform: "instagram",
    }),
    ["Started automatically", "Failed: Instagram rejected the video format"],
  ],
  [
    attempt({ trigger: "manual", status: "succeeded", platform: "youtube" }),
    ["Started manually", "Published on YouTube"],
  ],
  [
    attempt({
      status: "failed",
      requires_manual_review: true,
      platform: "threads",
    }),
    ["Started manually", "Result uncertain: Threads may have published it"],
  ],
  [
    attempt({
      status: "succeeded",
      platform: "tiktok",
      details: { delivered_to_inbox: true },
    }),
    ["Started manually", "Sent to your TikTok inbox"],
  ],
])("events are human, without codes", (input, texts) => {
  const events = attemptEvents(input);
  texts.forEach((text, index) => expect(events[index]).toContain(text));
  expect(events.join(" ")).not.toMatch(/ig_bad_format|attempt/i);
});

it("Activity is folded; technical details only under a second disclosure", async () => {
  const project = api.addProject({ name: "L4i4" });
  const media = api.addContent({ project_id: project.id });
  const account = api.addAccount({
    project_id: project.id,
    platform: "instagram",
    handle: "l4i4",
  });
  const post = api.addPublication({
    content_id: media.id,
    account_id: account.id,
  });
  api.startAttempt(api.publications.find((record) => record.id === post.id)!);
  api.failAttempt(
    post.id,
    "ig_media_rejected",
    "Instagram rejected the video format",
  );
  setHealth(api, project.id);
  const user = userEvent.setup();
  renderRoute(`/p/${project.id}/posts/${post.id}`);
  const section = (
    await screen.findByRole("heading", { name: "Activity" })
  ).closest("section")!;

  const toggle = within(section).getByRole("button", {
    name: "Show activity (1)",
  });
  expect(toggle).toHaveAttribute("aria-expanded", "false");
  await user.click(toggle);
  expect(
    await within(section).findByText(
      /Failed: Instagram rejected the video format/,
    ),
  ).toBeInTheDocument();
  expect(within(section).getByText("ig_media_rejected")).not.toBeVisible();
  await user.click(
    within(section).getByRole("button", { name: "Technical details" }),
  );
  expect(within(section).getByText("ig_media_rejected")).toBeVisible();
});

async function openTechnicalDetails(legacy: boolean) {
  const project = api.addProject({ name: "L4i4" });
  const media = api.addContent({
    project_id: project.id,
    checksum: "sent-file-sha",
  });
  const account = api.addAccount({
    project_id: project.id,
    platform: "youtube",
    handle: "l4i4",
  });
  const post = api.addPublication({
    content_id: media.id,
    account_id: account.id,
  });
  api.startAttempt(api.publications.find((record) => record.id === post.id)!);
  api.failAttempt(post.id, "yt_upload_failed", "The upload failed");
  const [recorded] = api.publicationAttempts.get(post.id)!;
  if (legacy) {
    // Attempts recorded before Feature 019 have no checksum.
    delete recorded.submitted.file_checksum;
  }
  // The Media's file changes afterwards (e.g. Remove metadata).
  api.contents.find((item) => item.id === media.id)!.publish_file.checksum =
    "current-media-sha";
  setHealth(api, project.id);
  const user = userEvent.setup();
  renderRoute(`/p/${project.id}/posts/${post.id}`);
  const section = (
    await screen.findByRole("heading", { name: "Activity" })
  ).closest("section")!;
  await user.click(
    within(section).getByRole("button", { name: /Show activity/ }),
  );
  await user.click(
    await within(section).findByRole("button", { name: "Technical details" }),
  );
  return section;
}

it("Technical details show the checksum of the file the attempt sent, never the Media's current one", async () => {
  const section = await openTechnicalDetails(false);
  expect(within(section).getByText("File checksum (SHA-256)")).toBeVisible();
  expect(within(section).getByText("sent-file-sha")).toBeVisible();
  expect(within(section).queryByText("current-media-sha")).toBeNull();
});

it("an older attempt without a checksum shows no checksum row", async () => {
  const section = await openTechnicalDetails(true);
  expect(within(section).getByText("yt_upload_failed")).toBeVisible();
  expect(within(section).queryByText(/File checksum/)).toBeNull();
  expect(within(section).queryByText("current-media-sha")).toBeNull();
});

it("a setup error reads as human copy; the original text stays in Technical details", async () => {
  const raw =
    "Telegram is not configured. Add your api_id and api_hash to the local Telegram app file (see docs/telegram.md).";
  const events = attemptEvents(
    attempt({
      status: "failed",
      platform: "telegram",
      error: { code: "telegram_not_configured", message: raw },
    }),
  );
  expect(events[1]).toContain("Failed: Telegram connection needs setup.");
  expect(events.join(" ")).not.toMatch(/api_id|docs\//);

  const project = api.addProject({ name: "Tg" });
  const account = api.addAccount({
    project_id: project.id,
    platform: "telegram",
    handle: "news",
  });
  const post = api.addPublication({ content_id: null, account_id: account.id });
  api.startAttempt(api.publications.find((record) => record.id === post.id)!);
  api.failAttempt(post.id, "telegram_not_configured", raw);
  setHealth(api, project.id);
  const user = userEvent.setup();
  renderRoute(`/p/${project.id}/posts/${post.id}`);
  const section = (
    await screen.findByRole("heading", { name: "Activity" })
  ).closest("section")!;
  await user.click(
    within(section).getByRole("button", { name: /Show activity/ }),
  );
  expect(
    await within(section).findByText(
      /Failed: Telegram connection needs setup\./,
    ),
  ).toBeVisible();
  expect(within(section).getByText(raw)).not.toBeVisible();
  await user.click(
    within(section).getByRole("button", { name: "Technical details" }),
  );
  expect(within(section).getByText(raw)).toBeVisible();
});
