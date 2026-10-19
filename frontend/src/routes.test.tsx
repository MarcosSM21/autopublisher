import { act, cleanup, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { FakeApi } from "./test-fake-api.ts";
import { renderRoute } from "./test-utils.tsx";

const LAST_PROJECT_KEY = "autopublisher.lastProjectId";

let api: FakeApi;

beforeEach(() => {
  api = new FakeApi();
  api.install();
});

afterEach(() => {
  window.localStorage.clear();
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

function mainNav() {
  return screen.getByRole("navigation", { name: "Main" });
}

/** Two projects, each with one media and one post. */
function seed() {
  const own = api.addProject({ name: "L4i4" });
  const other = api.addProject({ name: "Other" });
  const ownAccount = api.addAccount({ project_id: own.id, platform: "x" });
  const otherAccount = api.addAccount({ project_id: other.id, platform: "x" });
  const media = api.addContent({ project_id: own.id, title: "Summer teaser" });
  const otherMedia = api.addContent({ project_id: other.id, title: "Foreign" });
  const post = api.addPublication({
    content_id: media.id,
    account_id: ownAccount.id,
  });
  const otherPost = api.addPublication({
    content_id: otherMedia.id,
    account_id: otherAccount.id,
  });
  return { own, other, media, otherMedia, post, otherPost };
}

describe("routes", () => {
  it("creates the first project from Home and lands on its Library", async () => {
    const user = userEvent.setup();
    const { router } = renderRoute("/");
    await screen.findByRole("heading", { name: "Create your first project" });
    expect(within(mainNav()).getByText("Library")).toHaveAttribute(
      "aria-disabled",
      "true",
    );

    await user.click(screen.getByRole("button", { name: "Create project" }));
    const dialog = screen.getByRole("dialog", { name: "New project" });
    await user.type(within(dialog).getByLabelText("Name"), "L4i4");
    await user.click(
      within(dialog).getByRole("button", { name: "Create project" }),
    );

    expect(
      await screen.findByRole("heading", { level: 1, name: "Library" }),
    ).toBeInTheDocument();
    expect(router.state.location.pathname).toBe("/p/1/library");
    expect(window.localStorage.getItem(LAST_PROJECT_KEY)).toBe("1");
  });

  it("lands on Library when opening a project", async () => {
    const { own } = seed();
    const { router } = renderRoute(`/p/${own.id}`);

    await screen.findByRole("heading", { level: 1, name: "Library" });
    expect(router.state.location.pathname).toBe(`/p/${own.id}/library`);
  });

  it("opens a media and a post from their URL", async () => {
    const { own, media, post } = seed();
    renderRoute(`/p/${own.id}/library/${media.id}`);
    expect(
      await screen.findByRole("heading", { level: 2, name: "Summer teaser" }),
    ).toBeInTheDocument();
    cleanup();

    renderRoute(`/p/${own.id}/posts/${post.id}`);
    expect(
      await screen.findByRole("region", { name: "Post details" }),
    ).toBeInTheDocument();
  });

  it("keeps the selection in the URL and follows back and forward", async () => {
    const { own, post } = seed();
    const user = userEvent.setup();
    const { router } = renderRoute("/");
    await screen.findByRole("link", { name: /^L4i4/ });

    await act(() => router.navigate(`/p/${own.id}/posts`));
    await user.click(await screen.findByRole("link", { name: /Summer/ }));
    expect(router.state.location.pathname).toBe(
      `/p/${own.id}/posts/${post.id}`,
    );
    await screen.findByRole("region", { name: "Post details" });

    await act(() => router.navigate(-1));
    expect(router.state.location.pathname).toBe(`/p/${own.id}/posts`);
    expect(
      screen.queryByRole("region", { name: "Post details" }),
    ).not.toBeInTheDocument();
    await act(() => router.navigate(-1));
    expect(router.state.location.pathname).toBe("/");
    await act(() => router.navigate(1));
    await act(() => router.navigate(1));
    expect(router.state.location.pathname).toBe(
      `/p/${own.id}/posts/${post.id}`,
    );
    expect(
      await screen.findByRole("region", { name: "Post details" }),
    ).toBeInTheDocument();
  });

  it.each([
    ["an unknown page", () => "/nowhere", "Go to Home"],
    ["a missing project", () => "/p/99/library", "Go to Home"],
    ["a non-numeric project", () => "/p/abc", "Go to Home"],
    [
      "an unknown project section",
      (ids: Ids) => `/p/${ids.own}/x`,
      "Back to Library",
    ],
    [
      "a missing media",
      (ids: Ids) => `/p/${ids.own}/library/999`,
      "Back to Library",
    ],
    [
      "a non-numeric media",
      (ids: Ids) => `/p/${ids.own}/library/abc`,
      "Back to Library",
    ],
    [
      "a media of another project",
      (ids: Ids) => `/p/${ids.own}/library/${ids.otherMedia}`,
      "Back to Library",
    ],
    [
      "a missing post",
      (ids: Ids) => `/p/${ids.own}/posts/999`,
      "Back to Posts",
    ],
    [
      "a non-numeric post",
      (ids: Ids) => `/p/${ids.own}/posts/1x`,
      "Back to Posts",
    ],
    [
      "a post of another project",
      (ids: Ids) => `/p/${ids.own}/posts/${ids.otherPost}`,
      "Back to Posts",
    ],
  ])("shows not found for %s", async (_label, path, action) => {
    const data = seed();
    const ids: Ids = {
      own: data.own.id,
      otherMedia: data.otherMedia.id,
      otherPost: data.otherPost.id,
    };
    const { router } = renderRoute(path(ids));

    expect(
      await screen.findByRole("heading", { level: 1, name: "Not found" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: action })).toBeInTheDocument();
    // Never a silent project change.
    expect(router.state.location.pathname).toBe(path(ids));
    expect(
      screen.queryByRole("region", { name: /details/ }),
    ).not.toBeInTheDocument();
  });

  it("remembers the last project and ignores an invalid one", async () => {
    const { own, other } = seed();
    renderRoute(`/p/${other.id}/posts`);
    await screen.findByRole("heading", { level: 1, name: "Posts" });
    expect(window.localStorage.getItem(LAST_PROJECT_KEY)).toBe(
      String(other.id),
    );
    cleanup();

    // From Home the project sections open the last project.
    renderRoute("/");
    await screen.findByRole("link", { name: /^L4i4/ });
    expect(
      await within(mainNav()).findByRole("link", { name: "Posts" }),
    ).toHaveAttribute("href", `/p/${other.id}/posts`);
    cleanup();

    // A stored project that no longer exists is cleared; Home falls back to the first.
    window.localStorage.setItem(LAST_PROJECT_KEY, "99");
    renderRoute("/p/99/library");
    await screen.findByRole("heading", { level: 1, name: "Not found" });
    expect(window.localStorage.getItem(LAST_PROJECT_KEY)).toBeNull();
    cleanup();

    window.localStorage.setItem(LAST_PROJECT_KEY, "garbage");
    renderRoute("/");
    await screen.findByRole("link", { name: /^L4i4/ });
    expect(
      await within(mainNav()).findByRole("link", { name: "Library" }),
    ).toHaveAttribute("href", `/p/${own.id}/library`);
  });

  it("works when the browser storage throws", async () => {
    const { own } = seed();
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    renderRoute(`/p/${own.id}/library`);

    expect(
      await screen.findByRole("heading", { level: 1, name: "Library" }),
    ).toBeInTheDocument();
  });

  it("keeps editing and deactivating the project in its header", async () => {
    const { own } = seed();
    const user = userEvent.setup();
    renderRoute(`/p/${own.id}/accounts`);
    await screen.findByRole("link", { name: "Add account" });
    const header = screen.getByRole("region", { name: "Project" });

    await user.click(
      within(header).getByRole("button", { name: "Project actions" }),
    );
    await user.click(screen.getByRole("button", { name: "Edit project" }));
    const form = screen.getByRole("form", { name: "Edit project" });
    await user.clear(within(form).getByLabelText("Name"));
    await user.type(within(form).getByLabelText("Name"), "L4i4 Studio");
    await user.click(within(form).getByRole("button", { name: "Save" }));
    expect(await within(header).findByText("L4i4 Studio")).toBeInTheDocument();
    // The shell's project selector follows without leaving the page.
    expect(
      await screen.findByRole("option", { name: "L4i4 Studio" }),
    ).toBeInTheDocument();

    await user.click(
      screen.getByRole("button", { name: "Deactivate project" }),
    );
    expect(
      await screen.findByText("Reactivate this project to add accounts."),
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Activate project" }));
    expect(
      await screen.findByRole("link", { name: "Add account" }),
    ).toBeInTheDocument();
  });
});

interface Ids {
  own: number;
  otherMedia: number;
  otherPost: number;
}
