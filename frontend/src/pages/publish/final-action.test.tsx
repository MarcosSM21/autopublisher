import {
  act,
  cleanup,
  fireEvent,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { FakeApi } from "../../test-fake-api.ts";
import type { Account, Content, Project, Publication } from "../../types.ts";
import {
  addTelegram,
  openPublish,
  publishPath,
  setHealth,
  writes,
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
    description: "Clip",
  });
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function telegramDrafts(count: number): Publication[] {
  return Array.from({ length: count }, (_, index) =>
    api.addPublication({
      content_id: media.id,
      account_id: addTelegram(api, project.id, `ch${index + 1}`).id,
    }),
  );
}

function tiktokDraft(): { account: Account; post: Publication } {
  const account = api.addAccount({
    project_id: project.id,
    platform: "tiktok",
    handle: "cyber",
  });
  const post = api.addPublication({
    content_id: media.id,
    account_id: account.id,
  });
  api.tiktokOptions.set(post.id, {
    mode: "DIRECT_POST",
    privacy_level: "SELF_ONLY",
    allow_comment: false,
    allow_duet: false,
    allow_stitch: false,
    commercial_disclosure_enabled: false,
    brand_organic_toggle: false,
    brand_content_toggle: false,
    is_aigc: false,
  });
  return { account, post };
}

async function openTask(posts: Publication[]) {
  setHealth(api, project.id);
  const view = await openPublish(
    publishPath(
      project.id,
      media.id,
      posts.map((post) => post.id),
    ),
  );
  await screen.findByRole("heading", {
    level: 2,
    name: /Review|Still to finish/,
  });
  // Wait for every card to know its state.
  await waitFor(() =>
    expect(
      screen.queryAllByText("Checking", { selector: ".ap-badge *, .ap-badge" }),
    ).toEqual([]),
  );
  return view;
}

function calls(method: string, suffix: string) {
  return writes(api).filter(
    (request) => request.method === method && request.path.endsWith(suffix),
  );
}

function actionWrites() {
  return writes(api).filter((request) =>
    /\/(publish|tiktok-consent)$|^\/publications\/\d+$/.test(request.path),
  );
}

async function chooseSchedule(
  user: { click: (element: Element) => Promise<void> },
  value: string,
) {
  await user.click(screen.getByRole("radio", { name: "Schedule" }));
  fireEvent.change(screen.getByLabelText(/Date and time/), {
    target: { value },
  });
}

describe("When and the CTA", () => {
  it("Schedule shows the time zone, a readable date and warns when automation is paused", async () => {
    api.automation.paused = true;
    const [draft] = telegramDrafts(1);
    const { user } = await openTask([draft]);
    expect(screen.getByRole("radio", { name: "Now" })).toBeChecked();
    expect(
      screen.getByRole("button", { name: "Publish to 1 destination" }),
    ).toBeEnabled();

    await chooseSchedule(user, "2099-01-01T10:00");
    expect(
      screen.getByText(
        `Time zone: ${Intl.DateTimeFormat().resolvedOptions().timeZone}`,
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        new Date("2099-01-01T10:00").toLocaleString(undefined, {
          dateStyle: "full",
          timeStyle: "short",
        }),
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        "AutoPublisher will publish these posts automatically at this time.",
      ),
    ).toBeInTheDocument();
    expect(screen.getByText(/Automation is paused/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open Settings" })).toHaveAttribute(
      "href",
      "/settings",
    );
    expect(
      screen.getByRole("button", { name: "Schedule 1 post" }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Save as draft/ })).toBeNull();
  });

  it("counts only the Drafts of a mixed set", async () => {
    const drafts = telegramDrafts(2);
    const published = api.addPublication({
      content_id: media.id,
      account_id: addTelegram(api, project.id, "done").id,
      status: "published",
    });
    await openTask([published, ...drafts]);
    expect(
      screen.getByRole("button", { name: "Publish to 2 destinations" }),
    ).toBeEnabled();
  });
});

describe("validation before anything starts", () => {
  it("one Draft with problems: nothing starts, the summary is focused and links to it", async () => {
    const youtube = api.addAccount({
      project_id: project.id,
      platform: "youtube",
      handle: "chan",
    });
    const incomplete = api.addPublication({
      content_id: media.id,
      account_id: youtube.id,
    });
    const [ready] = telegramDrafts(1);
    const { post: tiktok } = tiktokDraft();
    const { user } = await openTask([ready, incomplete, tiktok]);

    const cta = screen.getByRole("button", {
      name: "Publish to 3 destinations",
    });
    expect(cta).toBeEnabled();
    await user.click(cta);

    const summary = await screen.findByRole("alert", { name: /Fix these/ });
    expect(summary).toHaveFocus();
    expect(actionWrites()).toEqual([]);
    expect(
      within(summary).getByRole("link", {
        name: /^YouTube @chan: YouTube needs 2 details/,
      }),
    ).toBeInTheDocument();
    const declaration = within(summary).getByRole("link", {
      name: "TikTok @cyber: TikTok declaration",
    });
    await user.click(declaration);
    expect(
      screen.getByRole("checkbox", { name: /I agree to the declaration/ }),
    ).toHaveFocus();

    await user.click(
      within(summary).getByRole("link", { name: /^YouTube @chan/ }),
    );
    const card = screen.getByRole("region", { name: /^YouTube/ });
    expect(card.contains(document.activeElement)).toBe(true);
  });

  it("a past date blocks Schedule with the error next to the field", async () => {
    const [draft] = telegramDrafts(1);
    const { user } = await openTask([draft]);
    await chooseSchedule(user, "2020-01-01T10:00");
    await user.click(screen.getByRole("button", { name: "Schedule 1 post" }));
    const summary = await screen.findByRole("alert", { name: /Fix these/ });
    expect(
      within(summary).getByRole("link", {
        name: "Choose a date and time in the future.",
      }),
    );
    expect(screen.getByLabelText(/Date and time/)).toHaveAttribute(
      "aria-invalid",
      "true",
    );
    expect(actionWrites()).toEqual([]);
  });
});

describe("Publish now", () => {
  it("a start that fails stops only that Post; the result is partial, never 'Publish failed'", async () => {
    const drafts = telegramDrafts(3);
    api.failRequest("POST", `/publications/${drafts[1].id}/publish`, 409, {
      error: {
        code: "account_inactive",
        message: "Reactivate the account first.",
      },
    });
    const { user } = await openTask(drafts);
    await user.click(
      screen.getByRole("button", { name: "Publish to 3 destinations" }),
    );

    const results = await screen.findByRole("region", { name: "Results" });
    await within(results).findByText("2 publishing · 1 didn't start");
    expect(calls("POST", "/publish").map((request) => request.path)).toEqual(
      drafts.map((post) => `/publications/${post.id}/publish`),
    );
    expect(
      within(results).getByText("Reactivate the account first."),
    ).toBeInTheDocument();
    expect(screen.queryByText(/Publish failed/)).toBeNull();
    expect(screen.getByRole("heading", { name: "Results" })).toHaveFocus();
    // The one that didn't start is still a Draft, ready to retry.
    expect(
      screen.getByRole("button", { name: "Publish to 1 destination" }),
    ).toBeInTheDocument();

    // Later: one fails on the platform, the other is published.
    act(() => {
      api.succeedAttempt(drafts[0].id);
      api.failAttempt(drafts[2].id, "upload_failed", "The upload failed.");
    });
    await within(results).findByText(
      "1 published · 1 failed · 1 didn't start",
      undefined,
      { timeout: 3000 },
    );
    const rows = within(results).getAllByRole("listitem");
    expect(
      within(rows[0]).queryByRole("link", { name: /Open post/ }),
    ).toBeNull();
    expect(
      within(rows[2]).getByRole("link", { name: /Open post/ }),
    ).toBeInTheDocument();
  });

  it("a Post already Published by the start is emphasised once in Results (Feature 026)", async () => {
    const [draft] = telegramDrafts(1);
    api.succeedOnPublish.add(draft.id);
    const { user } = await openTask([draft]);
    await user.click(
      screen.getByRole("button", { name: "Publish to 1 destination" }),
    );

    const results = await screen.findByRole("region", { name: "Results" });
    await within(results).findByText("1 published");
    expect(screen.getByRole("heading", { name: "Results" })).toHaveFocus();
    const badge = within(results).getByText("Published").closest(".ap-badge")!;
    expect(badge).toHaveAttribute("data-emphasis");
    expect(badge).not.toHaveAttribute("data-activity");

    fireEvent.animationEnd(badge, { animationName: "ap-badge-emphasis" });
    expect(badge).not.toHaveAttribute("data-emphasis");
    // The task keeps rendering (focus handled, polls): it never comes back.
    await act(() => new Promise((resolve) => setTimeout(resolve, 50)));
    expect(
      within(results).getByText("Published").closest(".ap-badge"),
    ).not.toHaveAttribute("data-emphasis");
    expect(within(results).getByText("1 published")).toHaveAttribute(
      "aria-live",
      "polite",
    );
    expect(screen.getByRole("heading", { name: "Results" })).toHaveFocus();
  });

  it("records the TikTok declaration right before publishing, and only once", async () => {
    const [telegram] = telegramDrafts(1);
    const { post: tiktok } = tiktokDraft();
    const { user } = await openTask([tiktok, telegram]);
    const checkbox = await screen.findByRole("checkbox", {
      name: /I agree to the declaration/,
    });
    expect(checkbox).not.toBeChecked();
    await user.click(checkbox);
    expect(calls("POST", "/tiktok-consent")).toEqual([]);

    await user.click(
      screen.getByRole("button", { name: "Publish to 2 destinations" }),
    );
    await screen.findByRole("region", { name: "Results" });
    expect(actionWrites().map((request) => request.path)).toEqual([
      `/publications/${tiktok.id}/tiktok-consent`,
      `/publications/${tiktok.id}/publish`,
      `/publications/${telegram.id}/publish`,
    ]);
    // No second confirmation of any kind.
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("a stale declaration: that Post didn't start and asks again; the others continue", async () => {
    const [telegram] = telegramDrafts(1);
    const { post: tiktok } = tiktokDraft();
    const { user } = await openTask([tiktok, telegram]);
    await user.click(
      await screen.findByRole("checkbox", {
        name: /I agree to the declaration/,
      }),
    );
    api.failRequest("POST", `/publications/${tiktok.id}/tiktok-consent`, 409, {
      error: { code: "tiktok_consent_stale", message: "Changed." },
    });
    await user.click(
      screen.getByRole("button", { name: "Publish to 2 destinations" }),
    );

    const results = await screen.findByRole("region", { name: "Results" });
    await within(results).findByText("1 publishing · 1 didn't start");
    expect(
      within(results).getByText("Confirm the TikTok declaration again."),
    ).toBeInTheDocument();
    expect(calls("POST", "/publish").map((request) => request.path)).toEqual([
      `/publications/${telegram.id}/publish`,
    ]);
    expect(
      screen.getByRole("checkbox", { name: /I agree to the declaration/ }),
    ).not.toBeChecked();
  });

  it("leaving the page after the first start still sends the remaining starts", async () => {
    const drafts = telegramDrafts(3);
    const release = api.holdRequest(
      "POST",
      `/publications/${drafts[1].id}/publish`,
    );
    const { user, router } = await openTask(drafts);
    await user.click(
      screen.getByRole("button", { name: "Publish to 3 destinations" }),
    );
    await waitFor(() =>
      expect(calls("POST", "/publish").map((request) => request.path)).toEqual([
        `/publications/${drafts[0].id}/publish`,
      ]),
    );

    await act(() => router.navigate(`/p/${project.id}/library`));
    expect(
      screen.queryByRole("heading", { level: 1, name: "Publish" }),
    ).toBeNull();
    release();

    await waitFor(() =>
      expect(calls("POST", "/publish").map((request) => request.path)).toEqual(
        drafts.map((post) => `/publications/${post.id}/publish`),
      ),
    );
  });
});

describe("Schedule", () => {
  it("a failure after others were scheduled: no rollback, no navigation, retry the one left", async () => {
    const drafts = telegramDrafts(4);
    api.failRequest("PATCH", `/publications/${drafts[3].id}`, 409, {
      error: {
        code: "account_inactive",
        message: "Reactivate the account first.",
      },
    });
    const { user, router } = await openTask(drafts);
    await chooseSchedule(user, "2099-01-01T10:00");
    await user.click(screen.getByRole("button", { name: "Schedule 4 posts" }));

    const results = await screen.findByRole("region", { name: "Results" });
    await within(results).findByText("3 scheduled · 1 still a draft");
    expect(
      within(results).getByText("Reactivate the account first."),
    ).toBeInTheDocument();
    const patches = calls("PATCH", "");
    expect(patches).toHaveLength(4);
    for (const patch of patches) {
      expect(patch.body).toEqual({
        scheduled_at: new Date("2099-01-01T10:00").toISOString(),
        auto_publish_enabled: true,
      });
    }
    const states = drafts.map(
      (post) =>
        api.publications.find((record) => record.id === post.id)!.status,
    );
    expect(states).toEqual([
      "scheduled",
      "scheduled",
      "scheduled",
      "unscheduled",
    ]);
    expect(router.state.location.pathname).toBe(
      publishPath(project.id, media.id),
    );
    expect(
      screen.getByRole("region", { name: "Still to finish · 1" }),
    ).toBeInTheDocument();

    // Fix and retry: only the one left is scheduled.
    await user.click(screen.getByRole("button", { name: "Schedule 1 post" }));
    await within(results).findByText("4 scheduled");
    expect(calls("PATCH", "")).toHaveLength(5);
  });

  it("with automation paused the Posts are scheduled and shown as paused", async () => {
    api.automation.paused = true;
    const [draft] = telegramDrafts(1);
    const { user } = await openTask([draft]);
    await chooseSchedule(user, "2099-01-01T10:00");
    await user.click(screen.getByRole("button", { name: "Schedule 1 post" }));
    const results = await screen.findByRole("region", { name: "Results" });
    expect(
      await within(results).findByText("Scheduled · paused"),
    ).toBeInTheDocument();
  });
});
