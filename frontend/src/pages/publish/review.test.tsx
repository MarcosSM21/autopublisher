import { cleanup, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { FakeApi } from "../../test-fake-api.ts";
import type { Content, Project } from "../../types.ts";
import {
  addTelegram,
  openPublish,
  publishPath,
  setHealth,
} from "./test-publish.ts";

let api: FakeApi;
let project: Project;
let media: Content;

beforeEach(() => {
  api = new FakeApi();
  api.install();
  project = api.addProject({ name: "L4i4" });
  media = api.addContent({
    project_id: project.id,
    media_type: "video",
    media_format: "mp4",
  });
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function mixedSet() {
  const published = api.addPublication({
    content_id: media.id,
    account_id: addTelegram(api, project.id, "one").id,
    status: "published",
  });
  const failed = api.addPublication({
    content_id: media.id,
    account_id: addTelegram(api, project.id, "two").id,
    status: "failed",
  });
  const tiktok = api.addAccount({
    project_id: project.id,
    platform: "tiktok",
    handle: "cyber",
  });
  const needsAction = api.addPublication({
    content_id: media.id,
    account_id: tiktok.id,
    status: "awaiting_user_action",
  });
  const draft = api.addPublication({
    content_id: media.id,
    account_id: addTelegram(api, project.id, "four").id,
  });
  setHealth(api, project.id);
  return { published, failed, needsAction, draft };
}

it("a mixed set shows Results first, then Still to finish with only the Draft", async () => {
  const { published, failed, needsAction, draft } = mixedSet();
  await openPublish(
    publishPath(project.id, media.id, [
      published.id,
      failed.id,
      needsAction.id,
      draft.id,
    ]),
  );

  const results = await screen.findByRole("region", { name: "Results" });
  const rows = within(results).getAllByRole("listitem");
  expect(rows).toHaveLength(3);
  expect(
    within(results).getByText("1 published · 1 ready in TikTok · 1 failed"),
  ).toBeInTheDocument();
  expect(within(rows[0]).getByText("Published")).toBeInTheDocument();
  expect(within(rows[1]).getByText("Failed")).toBeInTheDocument();
  expect(within(rows[2]).getByText("Ready in TikTok")).toBeInTheDocument();
  // Open post only where there is a problem.
  expect(within(rows[0]).queryByRole("link", { name: /Open post/ })).toBeNull();
  expect(
    within(rows[1]).getByRole("link", { name: /Open post/ }),
  ).toHaveAttribute("href", `/p/${project.id}/posts/${failed.id}`);
  expect(
    within(results).getByRole("link", { name: "View posts" }),
  ).toBeInTheDocument();
  expect(
    within(results).getByRole("link", { name: "Back to Library" }),
  ).toBeInTheDocument();

  const review = screen.getByRole("region", { name: "Still to finish · 1" });
  expect(
    within(review).getAllByRole("region", { name: /^Telegram/ }),
  ).toHaveLength(1);
  expect(
    within(review).getByRole("button", { name: "Publish to 1 destination" }),
  ).toBeInTheDocument();
  // Results come before Review in the page.
  expect(
    results.compareDocumentPosition(review) & Node.DOCUMENT_POSITION_FOLLOWING,
  ).toBeTruthy();
});

it("a set without Drafts is a result page only", async () => {
  const { published, failed } = mixedSet();
  await openPublish(
    publishPath(project.id, media.id, [published.id, failed.id]),
  );
  await screen.findByRole("region", { name: "Results" });
  expect(
    screen.queryByRole("region", { name: /Review|Still to finish/ }),
  ).toBeNull();
  expect(
    screen.queryByRole("button", { name: /Publish to|Schedule/ }),
  ).toBeNull();
});
