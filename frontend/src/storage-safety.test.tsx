// The browser never keeps tokens, upload session URLs or execution data (SC-007).
// The only browser storage is the last project opened (src/ui-preferences.ts,
// key autopublisher.lastProjectId); sessionStorage, IndexedDB and cookies are
// never used. This test documents and enforces that (research §10).
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import AutomationStatus from "./components/AutomationStatus.tsx";
import InstagramConnectionPanel from "./components/InstagramConnectionPanel.tsx";
import ThreadsConnectionPanel from "./components/ThreadsConnectionPanel.tsx";
import { FakeApi, IG_REDIRECT_URI, TH_REDIRECT_URI } from "./test-fake-api.ts";
import { setHealth } from "./pages/publish/test-publish.ts";
import { renderRoute } from "./test-utils.tsx";

const sources = import.meta.glob<string>("./**/*.{ts,tsx}", {
  query: "?raw",
  import: "default",
  eager: true,
});

const BROWSER_STORAGE =
  /\b(localStorage|sessionStorage|indexedDB)\b|document\.cookie/;
const FORBIDDEN_STORAGE = /\b(sessionStorage|indexedDB)\b|document\.cookie/;
const LAST_PROJECT_KEY = "autopublisher.lastProjectId";

/** setItem may only have stored the last project opened. */
function expectOnlyLastProjectStored(setItem: {
  mock: { calls: unknown[][] };
}) {
  for (const [key] of setItem.mock.calls) {
    expect(key).toBe(LAST_PROJECT_KEY);
  }
}

afterEach(() => {
  window.localStorage.clear();
  cleanup();
  vi.useRealTimers();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("browser storage", () => {
  it("never keeps TikTok options, Creator Info or consents", async () => {
    const setItem = vi.spyOn(Storage.prototype, "setItem");
    const setCookie = vi.spyOn(Document.prototype, "cookie", "set");
    const api = new FakeApi();
    api.install();
    const project = api.addProject({ name: "Cyber" });
    const video = api.addContent({
      project_id: project.id,
      media_type: "video",
      media_format: "mp4",
    });
    const tiktok = api.addAccount({
      project_id: project.id,
      platform: "tiktok",
      handle: "cyberstudio",
    });
    const publication = api.addPublication({
      content_id: video.id,
      account_id: tiktok.id,
    });
    setHealth(api, project.id);
    const user = userEvent.setup();
    renderRoute(
      `/p/${project.id}/library/${video.id}/publish?posts=${publication.id}`,
    );

    const privacy = await screen.findByRole("group", {
      name: "Who can view this video?",
    });
    await user.click(within(privacy).getByRole("radio", { name: /Only me/ }));
    await user.click(
      within(
        screen.getByRole("group", { name: "AI-generated content?" }),
      ).getByRole("radio", { name: "No" }),
    );
    const declaration = await screen.findByRole("checkbox", {
      name: /I agree to the declaration above/,
    });
    await waitFor(() => expect(declaration).toBeEnabled());
    await user.click(declaration);
    await user.click(
      screen.getByRole("button", { name: "Publish to 1 destination" }),
    );
    await waitFor(() =>
      expect(api.tiktokConsents.has(publication.id)).toBe(true),
    );

    expectOnlyLastProjectStored(setItem);
    expect(setCookie).not.toHaveBeenCalled();
    expect(
      Object.keys(window.localStorage).filter(
        (key) => key !== LAST_PROJECT_KEY,
      ),
    ).toEqual([]);
    expect(window.sessionStorage.length).toBe(0);
  });

  it("is never written while sending to the TikTok inbox and checking it", async () => {
    const setItem = vi.spyOn(Storage.prototype, "setItem");
    const setCookie = vi.spyOn(Document.prototype, "cookie", "set");
    const api = new FakeApi();
    api.install();
    const project = api.addProject({ name: "Cyber" });
    const video = api.addContent({
      project_id: project.id,
      media_type: "video",
      media_format: "mp4",
    });
    const tiktok = api.addAccount({
      project_id: project.id,
      platform: "tiktok",
      handle: "cyberstudio",
    });
    const created = api.addPublication({
      content_id: video.id,
      account_id: tiktok.id,
    });
    api.tiktokOptions.set(created.id, {
      mode: null,
      privacy_level: null,
      allow_comment: false,
      allow_duet: false,
      allow_stitch: false,
      commercial_disclosure_enabled: false,
      brand_organic_toggle: false,
      brand_content_toggle: false,
      is_aigc: null,
    });
    setHealth(api, project.id);
    const user = userEvent.setup();
    renderRoute(
      `/p/${project.id}/library/${video.id}/publish?posts=${created.id}`,
    );

    // Choose Upload to Inbox and send.
    await user.click(
      await screen.findByRole("radio", { name: "Send to my TikTok inbox" }),
    );
    await screen.findByText(
      "You'll get a TikTok inbox notification to finish the post.",
    );
    await user.click(
      screen.getByRole("button", { name: "Publish to 1 destination" }),
    );
    await waitFor(() =>
      expect(
        api.requests.filter((r) => r.path.endsWith("/publish")),
      ).toHaveLength(1),
    );
    cleanup();

    // Delivered: Ready in TikTok, then Check status from the Post.
    api.deliverToInbox(created.id);
    renderRoute(`/p/${project.id}/posts/${created.id}`);
    await user.click(
      await screen.findByRole("button", { name: "Check status" }),
    );
    await screen.findByText(
      "TikTok is still waiting for you to finish the post there.",
    );

    expectOnlyLastProjectStored(setItem);
    expect(setCookie).not.toHaveBeenCalled();
    expect(
      Object.keys(window.localStorage).filter(
        (key) => key !== LAST_PROJECT_KEY,
      ),
    ).toEqual([]);
    expect(window.sessionStorage.length).toBe(0);
  });

  it("is only referenced by the UI preferences module", () => {
    const appFiles = Object.entries(sources).filter(
      ([path]) =>
        !path.includes(".test.") &&
        !path.endsWith("test-fake-api.ts") &&
        !path.endsWith("test-setup.ts") &&
        !path.endsWith("test-utils.tsx"),
    );

    expect(appFiles.length).toBeGreaterThan(10);
    const offending = appFiles
      .filter(([path, source]) =>
        path === "./ui-preferences.ts"
          ? FORBIDDEN_STORAGE.test(source)
          : BROWSER_STORAGE.test(source),
      )
      .map(([path]) => path);
    expect(offending).toEqual([]);
    const preferences = sources["./ui-preferences.ts"];
    expect(preferences.match(/"autopublisher\.[\w.]+"/g)).toEqual([
      `"${LAST_PROJECT_KEY}"`,
    ]);
  });

  it("is never written during the whole publish flow", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const setItem = vi.spyOn(Storage.prototype, "setItem");
    const openDatabase = vi.fn();
    vi.stubGlobal("indexedDB", { open: openDatabase });
    const setCookie = vi.spyOn(Document.prototype, "cookie", "set");

    const api = new FakeApi();
    api.install();
    const project = api.addProject({ name: "Cyber" });
    const video = api.addContent({
      project_id: project.id,
      media_type: "video",
      media_format: "mp4",
      title: "Cybersecurity basics",
    });
    const account = api.addAccount({
      project_id: project.id,
      platform: "youtube",
      handle: "cyberchannel",
    });
    api.setConnection(account.id);
    setHealth(api, project.id);
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    renderRoute(`/p/${project.id}/library/${video.id}/publish`);

    // Compose → Continue → Review → Publish now → result.
    await user.click(
      await screen.findByRole("checkbox", { name: /YouTube @cyberchannel/ }),
    );
    await user.click(screen.getByRole("button", { name: "Continue" }));
    for (const name of ["Made for kids?", "Altered or synthetic content?"]) {
      await user.click(
        within(await screen.findByRole("group", { name })).getByRole("radio", {
          name: "No",
        }),
      );
    }
    await screen.findByText("Saved");
    await user.click(
      screen.getByRole("button", { name: "Publish to 1 destination" }),
    );
    const results = await screen.findByRole("region", { name: "Results" });
    const [publication] = api.publications;
    api.progressAttempt(publication.id, 500);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });
    api.succeedAttempt(publication.id);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });
    await within(results).findByText("1 published");

    expectOnlyLastProjectStored(setItem);
    expect(openDatabase).not.toHaveBeenCalled();
    expect(setCookie).not.toHaveBeenCalled();
  });

  it("is never written during the Instagram publish flow", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const setItem = vi.spyOn(Storage.prototype, "setItem");
    const setCookie = vi.spyOn(Document.prototype, "cookie", "set");

    const api = new FakeApi();
    api.install();
    const project = api.addProject({ name: "Cyber" });
    const image = api.addContent({
      project_id: project.id,
      media_type: "image",
      media_format: "png",
      description: "Summer drop.",
      hashtags: ["cyber"],
    });
    const account = api.addAccount({
      project_id: project.id,
      platform: "instagram",
      handle: "cyberstudio",
    });
    const publication = api.addPublication({
      content_id: image.id,
      account_id: account.id,
    });
    setHealth(api, project.id);
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    renderRoute(
      `/p/${project.id}/library/${image.id}/publish?posts=${publication.id}`,
    );

    const ai = await screen.findByRole("group", {
      name: "AI-generated content?",
    });
    await user.click(within(ai).getByRole("radio", { name: "No" }));
    await screen.findByText("Saved");
    await user.click(
      screen.getByRole("button", { name: "Publish to 1 destination" }),
    );
    const results = await screen.findByRole("region", { name: "Results" });
    api.setStage(publication.id, "processing");
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });
    api.succeedAttempt(publication.id);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });
    await within(results).findByText("1 published");

    expectOnlyLastProjectStored(setItem);
    expect(setCookie).not.toHaveBeenCalled();
  });

  it("is never written during the Threads publishing flows", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const setItem = vi.spyOn(Storage.prototype, "setItem");
    const setCookie = vi.spyOn(Document.prototype, "cookie", "set");

    const api = new FakeApi();
    api.install();
    const project = api.addProject({ name: "Cyber" });
    const threads = api.addAccount({
      project_id: project.id,
      platform: "threads",
      handle: "cyberstudio",
    });
    api.setThreadsConnection(threads.id);
    const image = api.addContent({
      project_id: project.id,
      media_type: "image",
      media_format: "png",
      description: "Summer drop.",
      hashtags: ["cyber"],
    });
    setHealth(api, project.id);
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });

    // Text post: Compose, Continue, Publish now and its result.
    renderRoute(`/p/${project.id}/posts/new`);
    await user.type(await screen.findByLabelText(/^Text/), "Hello Threads");
    await user.click(
      await screen.findByRole("checkbox", { name: /Threads @cyberstudio/ }),
    );
    await user.click(screen.getByRole("button", { name: "Continue" }));
    await user.click(
      await screen.findByRole("button", { name: "Publish to 1 destination" }),
    );
    const results = await screen.findByRole("region", { name: "Results" });
    const [text] = api.publications;
    api.setStage(text.id, "finalizing");
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });
    api.succeedAttempt(text.id);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });
    await within(results).findByText("1 published");
    cleanup();

    // Image: alt text option (saved on blur).
    const publication = api.addPublication({
      content_id: image.id,
      account_id: threads.id,
    });
    renderRoute(
      `/p/${project.id}/library/${image.id}/publish?posts=${publication.id}`,
    );
    const card = await screen.findByRole("region", { name: /^Threads/ });
    await user.click(within(card).getByRole("button", { name: "Details" }));
    await user.type(await within(card).findByLabelText(/Alt text/), "A sign");
    await user.tab();
    await within(card).findByText("Saved");

    expectOnlyLastProjectStored(setItem);
    expect(setCookie).not.toHaveBeenCalled();
  });

  it("is never written while automation runs, pauses or reports failures", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const setItem = vi.spyOn(Storage.prototype, "setItem");
    const setCookie = vi.spyOn(Document.prototype, "cookie", "set");

    const api = new FakeApi();
    api.install();
    const project = api.addProject({ name: "Cyber" });
    const video = api.addContent({
      project_id: project.id,
      media_type: "video",
      media_format: "mp4",
      title: "Cybersecurity basics",
    });
    const account = api.addAccount({
      project_id: project.id,
      platform: "youtube",
      handle: "cyberchannel",
    });
    api.setConnection(account.id);
    const publication = api.addPublication({
      content_id: video.id,
      account_id: account.id,
      scheduled_at: new Date(Date.now() + 60_000).toISOString(),
      auto_publish_enabled: true,
      auto_publish_error: {
        code: "youtube_unavailable",
        message: "YouTube is not available right now.",
        failed_at: "2026-10-07T18:00:30Z",
      },
    });
    setHealth(api, project.id);
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    render(<AutomationStatus />);
    renderRoute(`/p/${project.id}/posts/${publication.id}`);
    await screen.findByText(/Couldn't start automatically/);

    await user.click(
      await screen.findByRole("button", { name: "Pause automation" }),
    );
    await user.click(
      await screen.findByRole("button", { name: "Resume automation" }),
    );
    api.startScheduledAttempt(publication.id);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(15_000);
    });
    api.succeedAttempt(publication.id);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });
    await screen.findByRole("link", { name: "Open on YouTube" });

    expectOnlyLastProjectStored(setItem);
    expect(setCookie).not.toHaveBeenCalled();
  });

  it("is never written while connecting Instagram, and the pasted address is discarded", async () => {
    const setItem = vi.spyOn(Storage.prototype, "setItem");
    const openDatabase = vi.fn();
    vi.stubGlobal("indexedDB", { open: openDatabase });
    const setCookie = vi.spyOn(Document.prototype, "cookie", "set");
    vi.stubGlobal(
      "open",
      vi.fn(() => ({ location: { href: "" }, close: vi.fn() })),
    );
    const pasted = `${IG_REDIRECT_URI}?code=secret-code-9&state=secret-state-9#_`;

    const api = new FakeApi();
    api.install();
    const project = api.addProject({ name: "Cyber" });
    const account = api.addAccount({
      project_id: project.id,
      platform: "instagram",
      handle: "cyberstudio",
    });
    api.setInstagramConnection(account.id);
    api.nextInstagramOutcome = {
      status: "awaiting_confirmation",
      identity: {
        instagram_user_id: "17841400000000002",
        username: "new.account",
        account_type: "MEDIA_CREATOR",
        profile_picture_url: null,
      },
    };
    const user = userEvent.setup();
    render(<InstagramConnectionPanel account={account} projectActive />);
    const label = "Paste the address of the page Instagram opened";

    async function submit() {
      fireEvent.change(screen.getByLabelText(label), {
        target: { value: pasted },
      });
      await user.click(
        screen.getByRole("button", { name: "Complete connection" }),
      );
    }

    // A failed paste (error path) first, then the real one and the confirmation.
    await user.click(await screen.findByRole("button", { name: "Reconnect" }));
    api.failNext(400, {
      error: {
        code: "instagram_oauth_state_invalid",
        message: "The pasted address does not belong to this attempt.",
        fields: [],
      },
    });
    await submit();
    await screen.findByRole("alert");
    expect(screen.getByLabelText(label)).toHaveValue("");
    expect(document.body.innerHTML).not.toContain("secret-code-9");

    await submit();
    await user.click(
      await screen.findByRole("button", {
        name: "Replace with the new account",
      }),
    );
    await screen.findByText("@new.account");

    expect(document.body.innerHTML).not.toContain("secret-code-9");
    expect(document.body.innerHTML).not.toContain("secret-state-9");
    expectOnlyLastProjectStored(setItem);
    expect(openDatabase).not.toHaveBeenCalled();
    expect(setCookie).not.toHaveBeenCalled();
  });

  it("is never written while connecting Threads, and the pasted address is discarded", async () => {
    const setItem = vi.spyOn(Storage.prototype, "setItem");
    const openDatabase = vi.fn();
    vi.stubGlobal("indexedDB", { open: openDatabase });
    const setCookie = vi.spyOn(Document.prototype, "cookie", "set");
    vi.stubGlobal(
      "open",
      vi.fn(() => ({ location: { href: "" }, close: vi.fn() })),
    );
    const pasted = `${TH_REDIRECT_URI}?code=secret-code-7&state=secret-state-7#_`;

    const api = new FakeApi();
    api.install();
    const project = api.addProject({ name: "Cyber" });
    const account = api.addAccount({
      project_id: project.id,
      platform: "threads",
      handle: "cyberstudio",
    });
    api.setThreadsConnection(account.id);
    api.nextThreadsOutcome = {
      status: "awaiting_confirmation",
      identity: {
        threads_user_id: "25840000000000002",
        username: "new.account",
        display_name: null,
        profile_picture_url: null,
      },
    };
    const user = userEvent.setup();
    render(<ThreadsConnectionPanel account={account} projectActive />);
    const label = "Paste the address of the page Threads opened";

    async function submit() {
      fireEvent.change(screen.getByLabelText(label), {
        target: { value: pasted },
      });
      await user.click(
        screen.getByRole("button", { name: "Complete connection" }),
      );
    }

    // Error paths first (wrong state, then an unexpected failure that closes the
    // form), then the real paste and the confirmation.
    await user.click(await screen.findByRole("button", { name: "Reconnect" }));
    api.failNext(400, {
      error: {
        code: "threads_oauth_state_invalid",
        message: "The pasted address does not belong to this attempt.",
        fields: [],
      },
    });
    await submit();
    await screen.findByRole("alert");
    expect(screen.getByLabelText(label)).toHaveValue("");
    expect(document.body.innerHTML).not.toContain("secret-code-7");

    api.failNext(500, {
      error: {
        code: "internal_error",
        message: "An unexpected error occurred. Please try again.",
        fields: [],
      },
    });
    await submit();
    await screen.findByText("An unexpected error occurred. Please try again.");
    expect(screen.queryByLabelText(label)).not.toBeInTheDocument();
    expect(document.body.innerHTML).not.toContain("secret-code-7");

    await user.click(screen.getByRole("button", { name: "Reconnect" }));
    await submit();
    await user.click(
      await screen.findByRole("button", {
        name: "Replace with the new account",
      }),
    );
    await screen.findByText("@new.account");

    expect(document.body.innerHTML).not.toContain("secret-code-7");
    expect(document.body.innerHTML).not.toContain("secret-state-7");
    expectOnlyLastProjectStored(setItem);
    expect(openDatabase).not.toHaveBeenCalled();
    expect(setCookie).not.toHaveBeenCalled();
  });
});
