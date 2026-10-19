import { cleanup, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { FakeApi } from "../../test-fake-api.ts";
import { renderRoute } from "../../test-utils.tsx";
import type { Project, Publication } from "../../types.ts";
import { setHealth, setViewport, writes } from "../publish/test-publish.ts";

let api: FakeApi;
let project: Project;
let post: Publication;

beforeEach(() => {
  api = new FakeApi();
  api.install();
  setViewport(1280);
  project = api.addProject({ name: "L4i4" });
  const media = api.addContent({
    project_id: project.id,
    media_type: "video",
    media_format: "mp4",
  });
  const youtube = api.addAccount({
    project_id: project.id,
    platform: "youtube",
    handle: "chan",
  });
  post = api.addPublication({ content_id: media.id, account_id: youtube.id });
  api.youtubeOptions.set(post.id, {
    privacy_status: "private",
    made_for_kids: false,
    contains_synthetic_media: false,
    notify_subscribers: false,
  });
  api.startAttempt(api.publications.find((record) => record.id === post.id)!);
  api.failAttempt(post.id, "timeout", "No answer.", false);
  setHealth(api, project.id);
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

async function openCheck() {
  const user = userEvent.setup();
  renderRoute(`/p/${project.id}/posts/${post.id}`);
  const status = await screen.findByRole("region", { name: "Status" });
  await user.click(
    within(status).getByRole("button", { name: "Check result" }),
  );
  const dialog = await screen.findByRole("dialog", { name: "Check result" });
  return { user, dialog };
}

it("when the check resolves the result, the Post shows its determined state", async () => {
  api.reconcileOnCheck.add(post.id);
  const { user, dialog } = await openCheck();
  expect(
    await within(dialog).findByText(/The result is known now: Published/),
  ).toBeInTheDocument();
  expect(
    within(dialog).queryByRole("button", { name: "Publish again" }),
  ).toBeNull();
  await user.click(within(dialog).getByRole("button", { name: "Done" }));
  expect(
    await screen.findByText("Published", { selector: ".ap-status-panel *" }),
  ).toBeInTheDocument();
});

it("while uncertain, Publish again needs the acknowledgement and sends confirm_remote_checked", async () => {
  const { user, dialog } = await openCheck();
  const again = await within(dialog).findByRole("button", {
    name: "Publish again",
  });
  expect(again).toBeDisabled();
  expect(
    within(dialog).queryByRole("button", { name: /Reschedule|Move to drafts/ }),
  ).toBeNull();
  await user.click(
    within(dialog).getByRole("checkbox", {
      name: "I checked YouTube and this post was not published",
    }),
  );
  expect(again).toBeEnabled();
  await user.click(again);
  expect(
    await screen.findByText("Publishing", { selector: ".ap-status-panel *" }),
  ).toBeInTheDocument();
  expect(writes(api)).toEqual([
    {
      method: "POST",
      path: `/publications/${post.id}/publish`,
      body: { confirm_remote_checked: true },
    },
  ]);
});
