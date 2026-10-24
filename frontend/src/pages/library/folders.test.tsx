import { act, cleanup, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { FakeApi } from "../../test-fake-api.ts";
import { renderRoute } from "../../test-utils.tsx";
import type { LibraryFolderRead, Project } from "../../types.ts";

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

/** Five nested folders: A / B / C / D / E. */
function chain(): LibraryFolderRead[] {
  const folders: LibraryFolderRead[] = [];
  for (const name of ["A", "B", "C", "D", "E"]) {
    folders.push(
      api.addFolder({
        project_id: project.id,
        name,
        parent_id: folders.at(-1)?.id ?? null,
      }),
    );
  }
  return folders;
}

function folderPath(id: number) {
  return `/p/${project.id}/library/folders/${id}`;
}

async function open(path: string, title: string) {
  const user = userEvent.setup();
  const view = renderRoute(path);
  await screen.findByRole("heading", { level: 1, name: title });
  return { user, ...view };
}

function crumbs() {
  return screen.getByRole("navigation", { name: "Breadcrumb" });
}

function folderRequests(method: string) {
  return api.requests.filter(
    (request) =>
      request.method === method && request.path.includes("library-folders"),
  );
}

describe("Breadcrumb", () => {
  it("links every ancestor on wide screens, the current folder last", async () => {
    setViewport(1300);
    const folders = chain();
    await open(folderPath(folders[3].id), "D");

    const links = within(crumbs()).getAllByRole("link");
    expect(
      links.map((link) => [link.textContent, link.getAttribute("href")]),
    ).toEqual([
      ["Library", `/p/${project.id}/library`],
      ["A", folderPath(folders[0].id)],
      ["B", folderPath(folders[1].id)],
      ["C", folderPath(folders[2].id)],
    ]);
    const current = crumbs().querySelector('[aria-current="page"]');
    expect(current).toHaveTextContent("D");
    expect(current?.tagName).not.toBe("A");
  });

  it("collapses the middle levels behind … on phones, still reachable", async () => {
    setViewport(360);
    const folders = chain();
    const { user, router } = await open(folderPath(folders[4].id), "E");

    expect(
      within(crumbs())
        .getAllByRole("link")
        .map((link) => link.textContent),
    ).toEqual(["Library"]);
    const more = within(crumbs()).getByRole("button", {
      name: "Show 4 more folders",
    });
    expect(more).toHaveAttribute("aria-expanded", "false");

    await user.click(more);
    const hidden = within(crumbs()).getAllByRole("link").slice(1);
    expect(hidden.map((link) => link.textContent)).toEqual([
      "A",
      "B",
      "C",
      "D",
    ]);
    await user.click(hidden[1]);
    expect(router.state.location.pathname).toBe(folderPath(folders[1].id));
    expect(
      await screen.findByRole("heading", { level: 1, name: "B" }),
    ).toBeInTheDocument();
  });

  it("keeps two levels whole on phones", async () => {
    setViewport(360);
    const [a, b] = chain();
    await open(folderPath(b.id), "B");

    expect(
      within(crumbs())
        .getAllByRole("link")
        .map((link) => link.textContent),
    ).toEqual(["Library", "A"]);
    expect(within(crumbs()).queryByRole("button")).toBeNull();
    expect(a).toBeDefined();
  });
});

describe("New folder and Rename", () => {
  it("creates a top-level folder from the root", async () => {
    const { user } = await open(`/p/${project.id}/library`, "Library");

    await user.click(await screen.findByRole("button", { name: "New folder" }));
    const dialog = screen.getByRole("dialog", { name: "New folder" });
    await user.type(within(dialog).getByLabelText(/Name/), "  Cyber  ");
    await user.click(within(dialog).getByRole("button", { name: "Create" }));

    expect(
      await screen.findByRole("link", { name: /^Cyber\s*0 media/ }),
    ).toBeInTheDocument();
    expect(folderRequests("POST").map((request) => request.body)).toEqual([
      { name: "Cyber", parent_id: null },
    ]);
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("creates a subfolder inside the current folder, and shows a taken name inline", async () => {
    const cyber = api.addFolder({ project_id: project.id, name: "Cyber" });
    api.addFolder({
      project_id: project.id,
      name: "DDoS",
      parent_id: cyber.id,
    });
    const { user } = await open(folderPath(cyber.id), "Cyber");

    await user.click(screen.getByRole("button", { name: "Folder actions" }));
    await user.click(screen.getByRole("button", { name: "New folder" }));
    const dialog = screen.getByRole("dialog", { name: "New folder" });
    const name = within(dialog).getByLabelText(/Name/);
    await user.type(name, "ddos");
    await user.click(within(dialog).getByRole("button", { name: "Create" }));

    expect(
      await within(dialog).findByText(
        "A folder with this name already exists here.",
      ),
    ).toBeInTheDocument();
    expect(name).toHaveAttribute("aria-invalid", "true");

    await user.clear(name);
    await user.type(name, "MFA");
    await user.click(within(dialog).getByRole("button", { name: "Create" }));
    const subfolders = await screen.findByRole("list", { name: "Folders" });
    expect(
      await within(subfolders).findByRole("link", { name: /^MFA/ }),
    ).toBeInTheDocument();
    expect(folderRequests("POST").map((request) => request.body)).toEqual([
      { name: "ddos", parent_id: cyber.id },
      { name: "MFA", parent_id: cyber.id },
    ]);
  });

  it("rejects an empty name without a request, and reports folder_too_deep", async () => {
    const cyber = api.addFolder({ project_id: project.id, name: "Cyber" });
    api.failRequest("POST", `/projects/${project.id}/library-folders`, 409, {
      error: {
        code: "folder_too_deep",
        message: "Folders can be nested up to 5 levels.",
      },
    });
    const { user } = await open(folderPath(cyber.id), "Cyber");
    await user.click(screen.getByRole("button", { name: "Folder actions" }));
    await user.click(screen.getByRole("button", { name: "New folder" }));
    const dialog = screen.getByRole("dialog", { name: "New folder" });

    await user.type(within(dialog).getByLabelText(/Name/), "   ");
    await user.click(within(dialog).getByRole("button", { name: "Create" }));
    expect(within(dialog).getByText("Enter a folder name.")).toBeVisible();
    expect(folderRequests("POST")).toHaveLength(0);

    await user.type(within(dialog).getByLabelText(/Name/), "Deep");
    await user.click(within(dialog).getByRole("button", { name: "Create" }));
    expect(
      await within(dialog).findByText("Folders can be nested up to 5 levels."),
    ).toBeInTheDocument();

    await user.click(within(dialog).getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("offers no New folder at depth 5, and Rename only on user folders", async () => {
    const folders = chain();
    const { user } = await open(folderPath(folders[4].id), "E");
    await user.click(screen.getByRole("button", { name: "Folder actions" }));
    expect(screen.queryByRole("button", { name: "New folder" })).toBeNull();
    expect(screen.getByRole("button", { name: "Rename" })).toBeInTheDocument();
    cleanup();

    for (const [view, title] of [
      ["unsorted", "Unsorted"],
      ["all", "All media"],
    ]) {
      await open(`/p/${project.id}/library/${view}`, title);
      expect(
        screen.queryByRole("button", { name: "Folder actions" }),
      ).toBeNull();
      expect(screen.queryByRole("button", { name: "Rename" })).toBeNull();
      expect(
        screen.queryByRole("button", { name: "Delete folder" }),
      ).toBeNull();
      cleanup();
    }
  });

  it("renames, including a case-only change, and the name persists after a reload", async () => {
    const cyber = api.addFolder({ project_id: project.id, name: "cyber" });
    const { user } = await open(folderPath(cyber.id), "cyber");

    await user.click(screen.getByRole("button", { name: "Folder actions" }));
    await user.click(screen.getByRole("button", { name: "Rename" }));
    const dialog = screen.getByRole("dialog", { name: "Rename folder" });
    const name = within(dialog).getByLabelText(/Name/);
    expect(name).toHaveValue("cyber");
    await user.clear(name);
    await user.type(name, "Cyber");
    await user.click(within(dialog).getByRole("button", { name: "Save" }));

    expect(
      await screen.findByRole("heading", { level: 1, name: "Cyber" }),
    ).toBeInTheDocument();
    expect(folderRequests("PATCH").map((request) => request.body)).toEqual([
      { name: "Cyber" },
    ]);
    cleanup();

    await open(folderPath(cyber.id), "Cyber");
    expect(crumbs().querySelector('[aria-current="page"]')).toHaveTextContent(
      "Cyber",
    );
  });
});

describe("Delete folder", () => {
  async function deleteCurrentFolder(user: ReturnType<typeof userEvent.setup>) {
    await user.click(screen.getByRole("button", { name: "Folder actions" }));
    expect(
      screen.getByRole("button", { name: "Delete folder" }),
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Delete folder" }));
    return screen.getByRole("dialog", { name: "Delete folder?" });
  }

  it("removes the subtree, moves its media to Unsorted and returns to the parent", async () => {
    const [a, b, c] = chain();
    api.addContent({ project_id: project.id, title: "In B", folder_id: b.id });
    api.addContent({ project_id: project.id, title: "In C", folder_id: c.id });
    const { user, router } = await open(folderPath(b.id), "B");

    const dialog = await deleteCurrentFolder(user);
    const confirm = await within(dialog).findByRole("button", {
      name: "Delete",
    });
    // The backend's words, as is: no Media is lost.
    expect(
      [...dialog.querySelectorAll(".ap-delete-dialog p")].map(
        (line) => line.textContent,
      ),
    ).toEqual([
      "B",
      "3 subfolders will also be removed.",
      "2 media items will move to Unsorted.",
      "No media is deleted.",
    ]);
    await user.click(confirm);

    expect(router.state.location.pathname).toBe(folderPath(a.id));
    expect(await screen.findByText("Folder deleted.")).toBeInTheDocument();
    expect(
      await screen.findByRole("heading", { level: 1, name: "A" }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("list", { name: "Folders" })).toBeNull();

    // Both Media are still there, in Unsorted.
    await act(() => router.navigate(`/p/${project.id}/library/unsorted`));
    const grid = await screen.findByRole("list", { name: "Media" });
    expect(within(grid).getByText("In B")).toBeInTheDocument();
    expect(within(grid).getByText("In C")).toBeInTheDocument();
  });

  it("a top-level folder returns to the Library root without it", async () => {
    const cyber = api.addFolder({ project_id: project.id, name: "Cyber" });
    api.addFolder({ project_id: project.id, name: "Art" });
    const { user, router } = await open(folderPath(cyber.id), "Cyber");

    const dialog = await deleteCurrentFolder(user);
    await user.click(
      await within(dialog).findByRole("button", { name: "Delete" }),
    );

    expect(router.state.location.pathname).toBe(`/p/${project.id}/library`);
    expect(
      await screen.findByRole("link", { name: /Art/ }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Cyber/ })).toBeNull();

    // A stale link to it is Not found, never another folder.
    await act(() => router.navigate(folderPath(cyber.id)));
    expect(
      await screen.findByRole("link", { name: "Back to Library" }),
    ).toBeInTheDocument();
  });
});
