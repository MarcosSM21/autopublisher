import { act, cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { FakeApi } from "../test-fake-api.ts";
import { renderRoute } from "../test-utils.tsx";
import AppShell from "./AppShell.tsx";
import { FLASH_DURATION_MS } from "./Flash.tsx";

const LAST_PROJECT_KEY = "autopublisher.lastProjectId";

let api: FakeApi;

beforeEach(() => {
  api = new FakeApi();
  api.install();
});

afterEach(() => {
  window.localStorage.clear();
  cleanup();
  vi.unstubAllGlobals();
});

function setViewport(width: number) {
  vi.stubGlobal(
    "matchMedia",
    (query: string) =>
      ({
        matches: width >= Number(/min-width:\s*(\d+)px/.exec(query)?.[1] ?? 0),
        media: query,
        addEventListener: () => {},
        removeEventListener: () => {},
      }) as unknown as MediaQueryList,
  );
}

function mainNav() {
  return screen.getByRole("navigation", { name: "Main" });
}

/** The shell mounts once the session is known (Feature 020 bootstrap). */
function findMainNav() {
  return screen.findByRole("navigation", { name: "Main" });
}

function seed() {
  const own = api.addProject({ name: "L4i4" });
  const other = api.addProject({ name: "Other" });
  const account = api.addAccount({ project_id: own.id, platform: "x" });
  const media = api.addContent({ project_id: own.id, title: "Summer teaser" });
  const post = api.addPublication({
    content_id: media.id,
    account_id: account.id,
  });
  return { own, other, post };
}

describe("app shell", () => {
  it("marks the destination of the URL as current", async () => {
    const { own, post } = seed();
    renderRoute(`/p/${own.id}/posts/${post.id}`);
    const posts = await within(await findMainNav()).findByRole("link", {
      name: "Posts",
    });

    expect(posts).toHaveAttribute("aria-current", "page");
    for (const name of ["Home", "Library", "Accounts", "Settings"]) {
      expect(within(mainNav()).getByRole("link", { name })).not.toHaveAttribute(
        "aria-current",
      );
    }
  });

  it("opens the last project from global context", async () => {
    const { other } = seed();
    window.localStorage.setItem(LAST_PROJECT_KEY, String(other.id));
    renderRoute("/settings");

    expect(
      await within(await findMainNav()).findByRole("link", {
        name: "Accounts",
      }),
    ).toHaveAttribute("href", `/p/${other.id}/accounts`);
    expect(
      within(mainNav()).getByRole("link", { name: "Settings" }),
    ).toHaveAttribute("aria-current", "page");
    expect(screen.getByLabelText("Project")).toHaveValue(String(other.id));
  });

  it("puts Settings in More on phones", async () => {
    setViewport(375);
    seed();
    const user = userEvent.setup();
    const { router } = renderRoute("/");
    const more = await screen.findByRole("button", { name: "More" });

    expect(more).toHaveAttribute("aria-expanded", "false");
    await user.click(more);
    expect(more).toHaveAttribute("aria-expanded", "true");
    await user.keyboard("{Escape}");
    expect(more).toHaveAttribute("aria-expanded", "false");
    expect(more).toHaveFocus();

    await user.click(more);
    const region = document.getElementById(
      more.getAttribute("aria-controls")!,
    )!;
    await user.click(within(region).getByRole("link", { name: "Settings" }));
    expect(router.state.location.pathname).toBe("/settings");
    expect(
      await screen.findByRole("heading", { level: 1, name: "Settings" }),
    ).toBeInTheDocument();
    // Following the link closes the region.
    expect(screen.getByRole("button", { name: "More" })).toHaveAttribute(
      "aria-expanded",
      "false",
    );
  });

  it.each([
    [375, false],
    [768, false],
    [1280, true],
  ])(
    "renders one project selector at %ipx (in the sidebar: %s)",
    async (width, inSidebar) => {
      setViewport(width);
      seed();
      renderRoute("/");
      await screen.findByRole("option", { name: "L4i4" });

      const selectors = screen.getAllByLabelText("Project");
      expect(selectors).toHaveLength(1);
      expect(mainNav().contains(selectors[0])).toBe(inSidebar);
      expect(screen.queryByRole("button", { name: "More" }) !== null).toBe(
        width < 768,
      );
    },
  );

  it.each([
    [375, ["Skip to content", "Project", "More", "Home"]],
    [768, ["Skip to content", "Project", "Home"]],
    [1280, ["Skip to content", "Home", "Project", "Library"]],
  ])("keyboard order at %ipx follows the layout", async (width, expected) => {
    setViewport(width);
    seed();
    const user = userEvent.setup();
    renderRoute("/settings");
    await screen.findByRole("option", { name: "L4i4" });

    const order: string[] = [];
    for (let i = 0; i < expected.length; i++) {
      await user.tab();
      const el = document.activeElement as HTMLElement;
      order.push(
        el.tagName === "SELECT"
          ? ((el as HTMLSelectElement).labels[0]?.textContent ?? "")
          : (el.textContent ?? "").trim(),
      );
    }
    expect(order).toEqual(expected);
  });

  it.each([
    ["posts/:post", "posts"],
    ["accounts", "accounts"],
    ["library", "library"],
  ])(
    "switching project from %s keeps the %s section",
    async (from, section) => {
      const { own, other, post } = seed();
      const user = userEvent.setup();
      const { router } = renderRoute(
        `/p/${own.id}/${from.replace(":post", String(post.id))}`,
      );
      const selector = await screen.findByRole("combobox", { name: "Project" });
      await screen.findByRole("option", { name: "Other" });

      await user.selectOptions(selector, String(other.id));
      expect(router.state.location.pathname).toBe(`/p/${other.id}/${section}`);
      expect(screen.getByRole("combobox", { name: "Project" })).toHaveValue(
        String(other.id),
      );

      // Back returns to the previous project and URL.
      await act(() => router.navigate(-1));
      expect(router.state.location.pathname).toBe(
        `/p/${own.id}/${from.replace(":post", String(post.id))}`,
      );
    },
  );

  it.each([
    [375, true, false],
    [375, false, true],
    [768, true, true],
    [1280, true, true],
  ])(
    "at %ipx with taskMode %s the main navigation is shown: %s",
    async (width, taskMode, navShown) => {
      setViewport(width);
      seed();
      const router = createMemoryRouter(
        [
          {
            path: "/",
            element: <AppShell />,
            children: [
              {
                path: "task",
                handle: taskMode ? { taskMode: true } : undefined,
                element: <h1>Task</h1>,
              },
            ],
          },
        ],
        { initialEntries: ["/task"] },
      );
      render(<RouterProvider router={router} />);
      await screen.findByRole("heading", { level: 1, name: "Task" });

      expect(screen.queryByRole("navigation", { name: "Main" }) !== null).toBe(
        navShown,
      );
      // The TopBar (project selector) stays on phones and tablets.
      if (width < 1024) {
        expect(screen.getByLabelText("Project")).toBeInTheDocument();
      }
    },
  );
});

describe("flash", () => {
  function renderWithFlash() {
    const router = createMemoryRouter(
      [
        {
          path: "/",
          element: <AppShell />,
          children: [
            { path: "posts", element: <h1>Posts</h1> },
            { path: "other", element: <h1>Other</h1> },
          ],
        },
      ],
      {
        initialEntries: [
          "/other",
          { pathname: "/posts", state: { flash: "Post deleted." } },
        ],
        initialIndex: 1,
      },
    );
    render(<RouterProvider router={router} />);
    return router;
  }

  it("shows the navigation's message once, in a status region, then hides it", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      const router = renderWithFlash();
      await screen.findByRole("heading", { level: 1, name: "Posts" });
      const region = screen
        .getAllByRole("status")
        .find((node) => node.classList.contains("ap-flash"))!;
      expect(region).toHaveTextContent("Post deleted.");
      // Cleared from the history entry: Back/forward never repeat it.
      expect(router.state.location.pathname).toBe("/posts");
      expect(router.state.location.state).toBeNull();

      act(() => vi.advanceTimersByTime(FLASH_DURATION_MS));
      expect(region).toBeEmptyDOMElement();

      await act(() => router.navigate(-1));
      await act(() => router.navigate(1));
      expect(region).toBeEmptyDOMElement();
    } finally {
      vi.useRealTimers();
    }
  });
});
