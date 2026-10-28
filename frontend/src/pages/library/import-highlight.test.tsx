// The highlight of newly imported Media (Feature 026 T032/T033,
// contracts/ui.md §4). jsdom runs no CSS: the state is the attribute.
import {
  act,
  cleanup,
  fireEvent,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { FakeApi } from "../../test-fake-api.ts";
import { renderRoute } from "../../test-utils.tsx";
import type { Project } from "../../types.ts";

let api: FakeApi;
let project: Project;

beforeEach(() => {
  api = new FakeApi();
  api.install();
  project = api.addProject({ name: "L4i4" });
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function library(view = "") {
  return `/p/${project.id}/library${view}`;
}

async function open(path: string, title: string) {
  const user = userEvent.setup({ applyAccept: false });
  const view = renderRoute(path);
  await screen.findByRole("heading", { level: 1, name: title });
  return { user, ...view };
}

function makeFile(name: string, size = 10): File {
  return new File(["x".repeat(size)], name);
}

function grid() {
  return screen.getByRole("list", { name: "Media" });
}

function card(name: string): HTMLElement {
  return within(grid()).getByText(name).closest("a.ap-media-card")!;
}

/** The names of the cards that carry the highlight, in grid order. */
function highlighted(): string[] {
  return [
    ...document.querySelectorAll<HTMLElement>("[data-just-imported]"),
  ].map(
    (element) =>
      element.querySelector(".ap-media-card__title")?.textContent ?? "?",
  );
}

async function importInto(
  user: ReturnType<typeof userEvent.setup>,
  files: File[],
) {
  await user.upload(
    screen.getByLabelText<HTMLInputElement>("Choose files to import"),
    files,
  );
  return screen.findByRole("region", { name: "Import" });
}

describe("Import highlight", () => {
  it("marks only the Media this import created", async () => {
    api.addContent({
      project_id: project.id,
      title: null,
      original_filename: "old.png",
      size_bytes: 10,
    });
    api.addContent({ project_id: project.id, title: "Earlier" });
    // The first file's request fails as a whole (an API error for that file).
    api.failRequest("POST", `/projects/${project.id}/contents`, 500, {
      error: { code: "internal_error", message: "Server error.", fields: [] },
    });
    const { user } = await open(library("/unsorted"), "Unsorted");
    await screen.findByRole("list", { name: "Media" });

    const panel = await importInto(user, [
      makeFile("broken.png"),
      makeFile("new-a.png"),
      makeFile("old.png"),
      makeFile("notes.txt"),
      makeFile("new-b.png"),
    ]);

    await within(grid()).findByText("new-b.png");
    await waitFor(() => expect(highlighted()).toHaveLength(2));
    expect(highlighted().sort()).toEqual(["new-a.png", "new-b.png"]);
    // The duplicate's existing Media and the earlier ones are not marked.
    expect(card("old.png")).not.toHaveAttribute("data-just-imported");
    expect(card("Earlier")).not.toHaveAttribute("data-just-imported");
    // The panel is the same confirmation as before.
    expect(
      within(panel).getByText(/^2 imported · 1 duplicate · 2 rejected$/),
    ).toBeInTheDocument();
  });

  it("an import with nothing new marks nothing", async () => {
    api.addContent({
      project_id: project.id,
      original_filename: "old.png",
      size_bytes: 10,
    });
    const { user } = await open(library("/unsorted"), "Unsorted");
    await screen.findByRole("list", { name: "Media" });

    const panel = await importInto(user, [
      makeFile("old.png"),
      makeFile("notes.txt"),
    ]);
    await within(panel).findByText(/1 duplicate · 1 rejected/);
    expect(highlighted()).toEqual([]);
  });

  it("never reveals a Media the filters hide, and keeps the URL", async () => {
    api.addContent({ project_id: project.id, title: "Clip earlier" });
    const { user, router } = await open(
      library("/unsorted?q=clip"),
      "Unsorted",
    );
    await screen.findByRole("list", { name: "Media" });

    await importInto(user, [makeFile("clip-new.png"), makeFile("other.png")]);

    await waitFor(() => expect(highlighted()).toEqual(["clip-new.png"]));
    expect(within(grid()).queryByText("other.png")).toBeNull();
    expect(router.state.location.search).toBe("?q=clip");
  });

  it("removes the mark when its own animation ends, card by card", async () => {
    const { user } = await open(library("/unsorted"), "Unsorted");
    await importInto(user, [makeFile("a.png"), makeFile("b.png")]);
    await waitFor(() => expect(highlighted()).toHaveLength(2));

    // Unrelated animations (a badge, a child) never clear it.
    fireEvent.animationEnd(card("a.png"), { animationName: "ap-pulse" });
    expect(highlighted()).toHaveLength(2);

    fireEvent.animationEnd(card("a.png"), { animationName: "ap-highlight" });
    expect(highlighted()).toEqual(["b.png"]);
    fireEvent.animationEnd(card("b.png"), { animationName: "ap-highlight" });
    expect(highlighted()).toEqual([]);
  });

  it("a change of search or filter ends it, and returning does not bring it back", async () => {
    const { user } = await open(library("/unsorted"), "Unsorted");
    await importInto(user, [makeFile("a.png")]);
    await waitFor(() => expect(highlighted()).toEqual(["a.png"]));

    const searchbox = screen.getByRole("searchbox", { name: "Search media" });
    await user.type(searchbox, "a");
    expect(highlighted()).toEqual([]);
    await user.clear(searchbox);
    await within(grid()).findByText("a.png");
    expect(highlighted()).toEqual([]);
  });

  it("the sort alone keeps it: same Media, same snapshot", async () => {
    api.addContent({ project_id: project.id, title: "Earlier" });
    const { user } = await open(library("/unsorted"), "Unsorted");
    await importInto(user, [makeFile("a.png")]);
    await waitFor(() => expect(highlighted()).toEqual(["a.png"]));

    await user.selectOptions(
      screen.getByRole("combobox", { name: "Sort" }),
      "oldest",
    );
    expect(highlighted()).toEqual(["a.png"]);
  });

  it("any later reload ends it, even with the same query (Delete)", async () => {
    api.addContent({ project_id: project.id, title: "Earlier" });
    const { user } = await open(library("/unsorted"), "Unsorted");
    await importInto(user, [makeFile("a.png")]);
    await waitFor(() => expect(highlighted()).toEqual(["a.png"]));

    await user.click(
      within(grid()).getByRole("button", { name: "Media actions: Earlier" }),
    );
    await user.click(
      within(grid()).getByRole("button", { name: "Delete media" }),
    );
    const dialog = screen.getByRole("dialog", { name: "Delete media?" });
    await user.click(
      await within(dialog).findByRole("button", { name: "Delete" }),
    );
    await waitFor(() =>
      expect(within(grid()).queryByText("Earlier")).toBeNull(),
    );
    expect(highlighted()).toEqual([]);
  });

  it("a Media hidden at import time is never highlighted later", async () => {
    api.addContent({ project_id: project.id, title: "Clip earlier" });
    api.addContent({ project_id: project.id, title: "Clip gone" });
    const { user } = await open(library("/unsorted?q=clip"), "Unsorted");
    await screen.findByRole("list", { name: "Media" });

    // 1–2. Imported, but hidden by q: nothing is marked.
    const panel = await importInto(user, [makeFile("hidden.png")]);
    await within(panel).findByText(/1 imported/);
    expect(within(grid()).queryByText("hidden.png")).toBeNull();
    expect(highlighted()).toEqual([]);

    // 3. It now matches q, and the view reloads with exactly the same query.
    api.contents.find(
      (content) => content.original_filename === "hidden.png",
    )!.title = "Clip new";
    await user.click(
      within(grid()).getByRole("button", { name: "Media actions: Clip gone" }),
    );
    await user.click(
      within(grid()).getByRole("button", { name: "Delete media" }),
    );
    const dialog = screen.getByRole("dialog", { name: "Delete media?" });
    await user.click(
      await within(dialog).findByRole("button", { name: "Delete" }),
    );

    // 4. Visible, and still not highlighted.
    expect(await within(grid()).findByText("Clip new")).toBeInTheDocument();
    expect(highlighted()).toEqual([]);
  });

  it("another view never inherits it", async () => {
    const { user, router } = await open(library("/unsorted"), "Unsorted");
    await importInto(user, [makeFile("a.png")]);
    await waitFor(() => expect(highlighted()).toEqual(["a.png"]));

    await act(() => router.navigate(library("/all")));
    await screen.findByRole("heading", { level: 1, name: "All media" });
    expect(await within(grid()).findByText("a.png")).toBeInTheDocument();
    expect(highlighted()).toEqual([]);
  });

  it("never moves focus or selection", async () => {
    api.addContent({ project_id: project.id, title: "Earlier" });
    const { user } = await open(library("/unsorted"), "Unsorted");
    await screen.findByRole("list", { name: "Media" });

    await importInto(user, [makeFile("a.png")]);
    await waitFor(() => expect(highlighted()).toEqual(["a.png"]));
    // Where the import already left it (the main content), not on a card.
    const focused = document.activeElement;
    expect(focused).toHaveAttribute("id", "main-content");
    expect(card("a.png")).not.toHaveAttribute("aria-current");
    expect(card("Earlier")).not.toHaveAttribute("aria-current");

    fireEvent.animationEnd(card("a.png"), { animationName: "ap-highlight" });
    expect(document.activeElement).toBe(focused);
    expect(card("a.png")).not.toHaveAttribute("aria-current");
  });

  it("in Select mode the checkbox card shows it, and nothing comes back after", async () => {
    api.addContent({ project_id: project.id, title: "Earlier" });
    const { user } = await open(library("/unsorted"), "Unsorted");
    await screen.findByRole("list", { name: "Media" });
    await user.click(screen.getByRole("button", { name: "Select" }));
    await user.click(screen.getByRole("checkbox", { name: /Earlier/ }));

    await importInto(user, [makeFile("a.png")]);
    await waitFor(() => expect(highlighted()).toEqual(["a.png"]));
    const label = within(grid()).getByText("a.png").closest("label")!;
    expect(label).toHaveClass("ap-media-card");
    expect(label).toHaveAttribute("data-just-imported");
    // Purely visual: the selection and the checkboxes are unchanged.
    const bar = screen.getByRole("region", { name: "Selection" });
    expect(bar).toHaveTextContent("1 selected");
    expect(screen.getByRole("checkbox", { name: /a\.png/ })).not.toBeChecked();

    fireEvent.animationEnd(label, { animationName: "ap-pulse" });
    expect(label).toHaveAttribute("data-just-imported");
    fireEvent.animationEnd(label, { animationName: "ap-highlight" });
    expect(highlighted()).toEqual([]);

    await user.click(within(bar).getByRole("button", { name: "Cancel" }));
    expect(within(grid()).getAllByRole("link").length).toBeGreaterThan(0);
    expect(highlighted()).toEqual([]);
  });

  it("the Library root has no grid and marks nothing", async () => {
    const { user, router } = await open(library(), "Library");

    const panel = await importInto(user, [makeFile("a.png")]);
    await within(panel).findByText(/1 imported/);
    expect(screen.queryByRole("list", { name: "Media" })).toBeNull();
    expect(document.querySelector("[data-just-imported]")).toBeNull();
    expect(router.state.location.pathname).toBe(library());
  });
});
