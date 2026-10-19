import {
  act,
  cleanup,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { createMemoryRouter, Link, Outlet, RouterProvider } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { PostDisplayState } from "../types.ts";
import Button from "./Button.tsx";
import DetailSurface from "./DetailSurface.tsx";
import EmptyState from "./EmptyState.tsx";
import { POST_STATUS } from "./status.ts";
import StatusBadge from "./StatusBadge.tsx";

/** Pretend the viewport is `width` px wide for `(min-width: …)` queries. */
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

function ItemsPage() {
  return (
    <main>
      <h1>Items</h1>
      <Link to="/items/1">Open item</Link>
      <Outlet />
    </main>
  );
}

function ItemDetail() {
  return (
    <DetailSurface title="Item 1" parentPath="/items">
      <button type="button">First action</button>
      <button type="button">Second action</button>
    </DetailSurface>
  );
}

function renderItems(path: string) {
  const router = createMemoryRouter(
    [
      {
        path: "/items",
        element: <ItemsPage />,
        children: [{ path: ":id", element: <ItemDetail /> }],
      },
    ],
    { initialEntries: [path] },
  );
  render(<RouterProvider router={router} />);
  return router;
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("DetailSurface", () => {
  it("as a drawer traps focus, closes with Escape and returns focus", async () => {
    setViewport(800);
    const user = userEvent.setup();
    const router = renderItems("/items");
    const trigger = screen.getByRole("link", { name: "Open item" });

    await user.click(trigger);

    const drawer = await screen.findByRole("dialog", { name: "Item 1" });
    expect(drawer).toContainElement(document.activeElement as HTMLElement);
    for (let step = 0; step < 4; step += 1) {
      await user.tab();
      expect(drawer).toContainElement(document.activeElement as HTMLElement);
    }

    await user.keyboard("{Escape}");

    expect(router.state.location.pathname).toBe("/items");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    // Radix restores focus right after the drawer unmounts.
    await waitFor(() => expect(trigger).toHaveFocus());
  });

  it("as a page goes back to the list", async () => {
    setViewport(375);
    const user = userEvent.setup();
    const router = renderItems("/items/1");

    expect(
      screen.getByRole("heading", { level: 1, name: "Item 1" }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Back" }));

    expect(router.state.location.pathname).toBe("/items");
  });

  it("as a side panel stays next to the list without being modal", async () => {
    setViewport(1280);
    const user = userEvent.setup();
    const router = renderItems("/items/1");

    const panel = screen.getByRole("complementary", { name: "Item 1" });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open item" })).toBeVisible();

    await user.click(within(panel).getByRole("button", { name: "Close" }));

    expect(router.state.location.pathname).toBe("/items");
  });
});

/** A viewport whose width can change, notifying `matchMedia` listeners. */
function resizableViewport(initial: number) {
  let width = initial;
  const listeners = new Set<() => void>();
  vi.stubGlobal("matchMedia", (query: string) => {
    const min = Number(/min-width:\s*(\d+)px/.exec(query)?.[1] ?? 0);
    return {
      get matches() {
        return width >= min;
      },
      media: query,
      addEventListener: (_: string, listener: () => void) =>
        listeners.add(listener),
      removeEventListener: (_: string, listener: () => void) =>
        listeners.delete(listener),
    } as unknown as MediaQueryList;
  });
  return (next: number) => {
    width = next;
    act(() => listeners.forEach((listener) => listener()));
  };
}

function Counter() {
  const [count, setCount] = useState(0);
  return (
    <button type="button" onClick={() => setCount(count + 1)}>
      Clicked {count}
    </button>
  );
}

function renderWideDetail(path: string) {
  const router = createMemoryRouter(
    [
      {
        path: "/items",
        element: <ItemsPage />,
        children: [
          {
            path: ":id",
            element: (
              <DetailSurface
                title="Item 1"
                parentPath="/items"
                panelFrom="xl"
                actions={<button type="button">Main action</button>}
              >
                <Counter />
              </DetailSurface>
            ),
          },
        ],
      },
    ],
    { initialEntries: [path] },
  );
  render(<RouterProvider router={router} />);
  return router;
}

describe("DetailSurface options", () => {
  it("with panelFrom xl is a drawer at 1100 px and a side panel at 1300 px", () => {
    setViewport(1100);
    renderWideDetail("/items/1");
    expect(screen.getByRole("dialog", { name: "Item 1" })).toBeInTheDocument();
    expect(screen.queryByRole("complementary")).not.toBeInTheDocument();
    cleanup();

    setViewport(1300);
    renderWideDetail("/items/1");
    const panel = screen.getByRole("complementary", { name: "Item 1" });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(
      within(panel).getByRole("button", { name: "Main action" }),
    ).toBeVisible();
  });

  it("keeps the default panel from lg (Accounts) and renders actions in every surface", () => {
    setViewport(1100);
    renderItems("/items/1");
    expect(
      screen.getByRole("complementary", { name: "Item 1" }),
    ).toBeInTheDocument();
    cleanup();

    setViewport(375);
    renderWideDetail("/items/1");
    expect(
      screen.getByRole("group", { name: "Item 1 actions" }),
    ).toContainElement(screen.getByRole("button", { name: "Main action" }));
  });

  it("keeps the content's state when the breakpoint changes", async () => {
    const resize = resizableViewport(1300);
    const user = userEvent.setup();
    renderWideDetail("/items/1");
    await user.click(screen.getByRole("button", { name: "Clicked 0" }));

    resize(375);

    expect(screen.queryByRole("complementary")).not.toBeInTheDocument();
    expect(
      screen.getByRole("heading", { level: 1, name: "Item 1" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Clicked 1" })).toBeVisible();
  });

  it("moves focus to the heading when opened from the list, not on a deep link", async () => {
    setViewport(1300);
    const user = userEvent.setup();
    renderWideDetail("/items/1");
    expect(
      screen.getByRole("heading", { level: 2, name: "Item 1" }),
    ).not.toHaveFocus();
    cleanup();

    renderWideDetail("/items");
    await user.click(screen.getByRole("link", { name: "Open item" }));
    expect(
      await screen.findByRole("heading", { level: 2, name: "Item 1" }),
    ).toHaveFocus();
  });
});

describe("EmptyState", () => {
  it("offers exactly one primary action and an optional link", () => {
    render(
      <RouterProvider
        router={createMemoryRouter([
          {
            path: "/",
            element: (
              <EmptyState
                title="No media yet"
                description="Import images or videos to start."
                action={<Button variant="primary">Import media</Button>}
                secondary={{ to: "/help", label: "Learn more" }}
              />
            ),
          },
        ])}
      />,
    );

    expect(screen.getByRole("heading", { name: "No media yet" })).toBeVisible();
    expect(screen.getAllByRole("button")).toHaveLength(1);
    expect(screen.getByRole("link", { name: "Learn more" })).toBeVisible();
  });
});

describe("StatusBadge", () => {
  it("always shows the state as text, with a hidden decorative icon", () => {
    const states = Object.keys(POST_STATUS) as PostDisplayState[];
    render(
      <ul>
        {states.map((state) => (
          <li key={state}>
            <StatusBadge post={state} />
          </li>
        ))}
      </ul>,
    );

    const labels = screen
      .getAllByRole("listitem")
      .map((item) => item.textContent);
    expect(labels).toEqual([
      "Draft",
      "Scheduled · automatic",
      "Scheduled · manual",
      "Scheduled · paused",
      "Publishing",
      "Published",
      "Failed",
      "Needs review",
      "Needs action",
      "Missed",
      "Cancelled",
    ]);
    for (const icon of document.querySelectorAll("svg")) {
      expect(icon).toHaveAttribute("aria-hidden", "true");
    }
  });
});
