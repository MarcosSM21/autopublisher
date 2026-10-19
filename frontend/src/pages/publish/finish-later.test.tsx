import { cleanup, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { FakeApi } from "../../test-fake-api.ts";
import type { Content, Project, Publication } from "../../types.ts";
import { openPublish, publishPath, setHealth, writes } from "./test-publish.ts";

let api: FakeApi;
let project: Project;
let media: Content;
let draft: Publication;

beforeEach(() => {
  api = new FakeApi();
  api.install();
  project = api.addProject({ name: "L4i4" });
  media = api.addContent({
    project_id: project.id,
    media_type: "video",
    media_format: "mp4",
  });
  const youtube = api.addAccount({
    project_id: project.id,
    platform: "youtube",
    handle: "chan",
  });
  draft = api.addPublication({ content_id: media.id, account_id: youtube.id });
  setHealth(api, project.id);
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const optionsPath = () => `/publications/${draft.id}/youtube-options`;

async function openReview() {
  const view = await openPublish(publishPath(project.id, media.id, [draft.id]));
  const group = await screen.findByRole("group", { name: "Made for kids?" });
  return { ...view, group };
}

it("waits for a pending save, then leaves for Posts → Drafts writing nothing else", async () => {
  const release = api.holdRequest("PUT", optionsPath());
  const { user, router, group } = await openReview();
  await user.click(within(group).getByRole("radio", { name: "No" }));

  await user.click(screen.getByRole("button", { name: "Finish later" }));
  expect(router.state.location.pathname).toBe(
    publishPath(project.id, media.id),
  );
  release();

  await waitFor(() =>
    expect(router.state.location.pathname).toBe(`/p/${project.id}/posts`),
  );
  expect(router.state.location.state).toEqual({ focus: "drafts" });
  // Only the option save: Finish later itself creates, schedules or arms nothing.
  expect(
    writes(api).map((request) => `${request.method} ${request.path}`),
  ).toEqual([`PUT ${optionsPath()}`]);
  expect(api.publications[0].status).toBe("unscheduled");
});

it("a save that failed asks to retry or discard before leaving", async () => {
  api.failRequest("PUT", optionsPath(), 500, {
    error: { code: "server_error", message: "Something went wrong." },
  });
  const { user, router, group } = await openReview();
  await user.click(within(group).getByRole("radio", { name: "No" }));
  expect(
    await screen.findByText(/Couldn't save: Something went wrong./),
  ).toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: "Finish later" }));
  const dialog = await screen.findByRole("dialog", {
    name: "Couldn't save 1 change",
  });
  expect(router.state.location.pathname).toBe(
    publishPath(project.id, media.id),
  );

  // Retry sends the change again; once saved, Finish later leaves.
  await user.click(within(dialog).getByRole("button", { name: "Retry" }));
  await waitFor(() =>
    expect(router.state.location.pathname).toBe(`/p/${project.id}/posts`),
  );
  expect(
    writes(api).filter((request) => request.path === optionsPath()),
  ).toHaveLength(2);
});

it("Discard and leave goes without the failed change", async () => {
  api.failRequest("PUT", optionsPath(), 500, {
    error: { code: "server_error", message: "Something went wrong." },
  });
  const { user, router, group } = await openReview();
  await user.click(within(group).getByRole("radio", { name: "No" }));
  await screen.findByText(/Couldn't save/);
  await user.click(screen.getByRole("button", { name: "Finish later" }));
  const dialog = await screen.findByRole("dialog", {
    name: "Couldn't save 1 change",
  });
  await user.click(
    within(dialog).getByRole("button", { name: "Discard and leave" }),
  );
  await waitFor(() =>
    expect(router.state.location.pathname).toBe(`/p/${project.id}/posts`),
  );
  expect(writes(api)).toHaveLength(1);
});

it("the CTA waits for the saves and won't start with one that failed", async () => {
  api.failRequest("PUT", optionsPath(), 500, {
    error: { code: "server_error", message: "Something went wrong." },
  });
  const { user, group } = await openReview();
  await user.click(within(group).getByRole("radio", { name: "No" }));
  await screen.findByText(/Couldn't save/);
  await user.click(
    screen.getByRole("button", { name: "Publish to 1 destination" }),
  );
  const summary = await screen.findByRole("alert", { name: /Fix these/ });
  expect(
    within(summary).getByRole("link", {
      name: "YouTube @chan: a change couldn't be saved. Retry it.",
    }),
  ).toBeInTheDocument();
  expect(writes(api).map((request) => request.method)).toEqual(["PUT"]);
});
