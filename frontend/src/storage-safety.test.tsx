// The browser never keeps tokens, upload session URLs or execution data (SC-007).
// AutoPublisher does not use localStorage, sessionStorage, IndexedDB or cookies at
// all: this test documents and enforces that.
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
import PublicationDetail from "./components/PublicationDetail.tsx";
import { FakeApi, IG_REDIRECT_URI } from "./test-fake-api.ts";

const sources = import.meta.glob<string>("./**/*.{ts,tsx}", {
  query: "?raw",
  import: "default",
  eager: true,
});

const BROWSER_STORAGE =
  /\b(localStorage|sessionStorage|indexedDB)\b|document\.cookie/;

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("browser storage", () => {
  it("is not referenced by the application code", () => {
    const appFiles = Object.entries(sources).filter(
      ([path]) =>
        !path.includes(".test.") &&
        !path.endsWith("test-fake-api.ts") &&
        !path.endsWith("test-setup.ts"),
    );

    expect(appFiles.length).toBeGreaterThan(10);
    const offending = appFiles
      .filter(([, source]) => BROWSER_STORAGE.test(source))
      .map(([path]) => path);
    expect(offending).toEqual([]);
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
    const publication = api.addPublication({
      content_id: video.id,
      account_id: account.id,
    });
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    render(<PublicationDetail publication={publication} onChanged={vi.fn()} />);

    for (const name of ["Made for kids", "Altered or synthetic content"]) {
      await user.click(
        within(await screen.findByRole("group", { name })).getByRole("radio", {
          name: "No",
        }),
      );
    }
    await user.click(
      screen.getByRole("button", { name: "Save YouTube options" }),
    );
    const publishNow = await screen.findByRole("button", {
      name: "Publish now",
    });
    await waitFor(() => expect(publishNow).toBeEnabled());
    await user.click(publishNow);
    const dialog = await screen.findByRole("dialog", { name: "Publish now" });
    const confirm = within(dialog).getByRole("button", { name: "Publish" });
    await waitFor(() => expect(confirm).toBeEnabled());
    await user.click(confirm);
    api.progressAttempt(publication.id, 500);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });
    api.succeedAttempt(publication.id);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });
    await screen.findByRole("link", { name: "Open on YouTube" });

    expect(setItem).not.toHaveBeenCalled();
    expect(openDatabase).not.toHaveBeenCalled();
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
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    render(
      <>
        <AutomationStatus />
        <PublicationDetail publication={publication} onChanged={vi.fn()} />
      </>,
    );

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

    expect(setItem).not.toHaveBeenCalled();
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
    expect(setItem).not.toHaveBeenCalled();
    expect(openDatabase).not.toHaveBeenCalled();
    expect(setCookie).not.toHaveBeenCalled();
  });
});
