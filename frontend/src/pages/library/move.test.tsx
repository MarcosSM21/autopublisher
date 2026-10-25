import { act, cleanup, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { FakeApi } from "../../test-fake-api.ts";
import { renderRoute } from "../../test-utils.tsx";
import type { LibraryFolderRead, Project } from "../../types.ts";

let api: FakeApi;
let project: Project;
let cyber: LibraryFolderRead;
let ddos: LibraryFolderRead;
let art: LibraryFolderRead;

beforeEach(() => {
  api = new FakeApi();
  api.install();
  project = api.addProject({ name: "L4i4" });
  cyber = api.addFolder({ project_id: project.id, name: "Cyber" });
  art = api.addFolder({ project_id: project.id, name: "Art" });
  ddos = api.addFolder({
    project_id: project.id,
    name: "DDoS",
    parent_id: cyber.id,
  });
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const library = () => `/p/${project.id}/library`;

async function open(path: string, title: string) {
  const user = userEvent.setup();
  const view = renderRoute(path);
  await screen.findByRole("heading", { level: 1, name: title });
  return { user, ...view };
}

function moveRequests() {
  return api.requests.filter((request) => request.path.endsWith("/move"));
}

function picker(name: string | RegExp) {
  return screen.getByRole("dialog", { name });
}

function destinations(dialog: HTMLElement) {
  return within(dialog)
    .getAllByRole("radio")
    .map((radio) => radio.closest("label")?.textContent);
}

describe("FolderPicker and Move from the detail", () => {
  it("lists Unsorted then the tree, marks the current folder and never offers All media", async () => {
    const media = api.addContent({
      project_id: project.id,
      title: "Clip",
      folder_id: ddos.id,
    });
    const { user } = await open(
      `${library()}/folders/${ddos.id}/${media.id}`,
      "DDoS",
    );

    expect(await screen.findByText("Folder: DDoS")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Move" }));
    const dialog = picker("Move media");
    // Depth-first, siblings by name: Art, Cyber, then DDoS under Cyber.
    expect(destinations(dialog)).toEqual([
      "Unsorted",
      "Art",
      "Cyber",
      "DDoSCurrent",
    ]);
    expect(within(dialog).queryByText("All media")).toBeNull();
    expect(
      within(dialog).getByRole("radio", { name: /DDoS/ }).closest("label"),
    ).toHaveAttribute("data-depth", "2");
    // Nothing to do until another destination is chosen.
    const moveHere = within(dialog).getByRole("button", { name: "Move here" });
    expect(moveHere).toBeDisabled();
    await user.click(within(dialog).getByRole("radio", { name: /DDoS/ }));
    expect(moveHere).toBeDisabled();
  });

  it("moves to Unsorted and follows the media there, showing its new location", async () => {
    const media = api.addContent({
      project_id: project.id,
      title: "Clip",
      folder_id: cyber.id,
    });
    const { user, router } = await open(
      `${library()}/folders/${cyber.id}/${media.id}`,
      "Cyber",
    );
    await screen.findByText("Folder: Cyber");

    await user.click(screen.getByRole("button", { name: "Move" }));
    const dialog = picker("Move media");
    await user.click(within(dialog).getByRole("radio", { name: "Unsorted" }));
    await user.click(within(dialog).getByRole("button", { name: "Move here" }));

    expect(await screen.findByText("Folder: Unsorted")).toBeInTheDocument();
    expect(router.state.location.pathname).toBe(
      `${library()}/unsorted/${media.id}`,
    );
    expect(
      screen.getByRole("heading", { level: 1, name: "Unsorted" }),
    ).toBeInTheDocument();
    expect(moveRequests().map((request) => request.body)).toEqual([
      { content_ids: [media.id], folder_id: null },
    ]);
    expect(screen.queryByRole("dialog", { name: "Move media" })).toBeNull();
  });

  it("moves to a folder from All media and stays there with the new label", async () => {
    const media = api.addContent({ project_id: project.id, title: "Clip" });
    const { user, router } = await open(
      `${library()}/all/${media.id}`,
      "All media",
    );
    await screen.findByText("Folder: Unsorted");

    await user.click(screen.getByRole("button", { name: "Move" }));
    const dialog = picker("Move media");
    await user.click(within(dialog).getByRole("radio", { name: "Art" }));
    await user.click(within(dialog).getByRole("button", { name: "Move here" }));

    expect(await screen.findByText("Folder: Art")).toBeInTheDocument();
    expect(router.state.location.pathname).toBe(`${library()}/all/${media.id}`);
    expect(api.contents[0].folder_id).toBe(art.id);
  });

  it("shows the error and changes nothing when the folder is gone", async () => {
    const media = api.addContent({ project_id: project.id, title: "Clip" });
    const { user } = await open(`${library()}/all/${media.id}`, "All media");
    await screen.findByText("Folder: Unsorted");

    await user.click(screen.getByRole("button", { name: "Move" }));
    const dialog = picker("Move media");
    await user.click(within(dialog).getByRole("radio", { name: "Art" }));
    api.folders = api.folders.filter((folder) => folder.id !== art.id);
    await user.click(within(dialog).getByRole("button", { name: "Move here" }));

    expect(await within(dialog).findByRole("alert")).toHaveTextContent(
      "Some of the media or the folder no longer exist. Nothing was moved.",
    );
    expect(api.contents[0].folder_id).toBeNull();
    expect(screen.getByText("Folder: Unsorted")).toBeInTheDocument();
  });
});

describe("Select mode", () => {
  it("moves 3 selected media with one request, then reloads and leaves Select", async () => {
    const ids = ["One", "Two", "Three", "Four"].map(
      (title) => api.addContent({ project_id: project.id, title }).id,
    );
    const { user } = await open(`${library()}/unsorted`, "Unsorted");
    await screen.findByRole("list", { name: "Media" });

    await user.click(screen.getByRole("button", { name: "Select" }));
    const bar = screen.getByRole("region", { name: "Selection" });
    expect(bar).toHaveTextContent("0 selected");
    // The bulk actions Move and Delete (Feature 022), then Cancel.
    expect(
      within(bar)
        .getAllByRole("button")
        .map((button) => button.textContent),
    ).toEqual(["Move", "Delete", "Cancel"]);
    expect(within(bar).getByRole("button", { name: "Move" })).toBeDisabled();
    expect(within(bar).getByRole("button", { name: "Delete" })).toBeDisabled();
    // Cards are checkboxes now, not links.
    expect(
      within(screen.getByRole("list", { name: "Media" })).queryAllByRole(
        "link",
      ),
    ).toHaveLength(0);

    for (const title of ["One", "Two", "Four"]) {
      await user.click(
        screen.getByRole("checkbox", { name: new RegExp(title) }),
      );
    }
    expect(bar).toHaveTextContent("3 selected");
    await user.click(within(bar).getByRole("button", { name: "Move" }));
    const dialog = picker("Move 3 media");
    expect(destinations(dialog)[0]).toBe("UnsortedCurrent");
    await user.click(within(dialog).getByRole("radio", { name: "Cyber" }));
    await user.click(within(dialog).getByRole("button", { name: "Move here" }));

    expect(
      await screen.findByRole("button", { name: "Select" }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Selection" })).toBeNull();
    expect(moveRequests().map((request) => request.body)).toEqual([
      { content_ids: [ids[0], ids[1], ids[3]], folder_id: cyber.id },
    ]);
    const cards = within(screen.getByRole("list", { name: "Media" }));
    expect(cards.getAllByRole("link")).toHaveLength(1);
    expect(cards.getByRole("link")).toHaveTextContent("Three");
  });

  it("keeps everything when one selected media no longer exists", async () => {
    const gone = api.addContent({ project_id: project.id, title: "Gone" });
    api.addContent({ project_id: project.id, title: "Stays" });
    const { user } = await open(`${library()}/all`, "All media");
    await screen.findByRole("list", { name: "Media" });
    await user.click(screen.getByRole("button", { name: "Select" }));
    await user.click(screen.getByRole("checkbox", { name: /Gone/ }));
    await user.click(screen.getByRole("checkbox", { name: /Stays/ }));
    api.contents = api.contents.filter((content) => content.id !== gone.id);

    await user.click(screen.getByRole("button", { name: "Move" }));
    const dialog = picker("Move 2 media");
    // In All media the selection may come from several folders: no Current.
    expect(within(dialog).queryByText("Current")).toBeNull();
    await user.click(within(dialog).getByRole("radio", { name: "Art" }));
    await user.click(within(dialog).getByRole("button", { name: "Move here" }));

    expect(await within(dialog).findByRole("alert")).toHaveTextContent(
      "Nothing was moved.",
    );
    expect(api.contents.every((content) => content.folder_id === null)).toBe(
      true,
    );
    // The list is read again: the missing one leaves the selection.
    expect(
      await screen.findByText("1 selected", { selector: "p" }),
    ).toBeInTheDocument();
  });

  it("Cancel clears the selection and gives the links back", async () => {
    api.addContent({ project_id: project.id, title: "One" });
    const { user } = await open(`${library()}/all`, "All media");
    await screen.findByRole("list", { name: "Media" });

    await user.click(screen.getByRole("button", { name: "Select" }));
    await user.click(screen.getByRole("checkbox", { name: /One/ }));
    await user.click(screen.getByRole("button", { name: "Cancel" }));

    expect(screen.queryByRole("region", { name: "Selection" })).toBeNull();
    expect(screen.getByRole("link", { name: /One/ })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Select" }));
    expect(screen.getByRole("checkbox", { name: /One/ })).not.toBeChecked();
    expect(moveRequests()).toHaveLength(0);
  });

  it("never keeps a selection when the project changes", async () => {
    api.addContent({ project_id: project.id, title: "Mine" });
    const other = api.addProject({ name: "Other" });
    api.addContent({ project_id: other.id, title: "Theirs" });
    const { user, router } = await open(`${library()}/all`, "All media");
    await screen.findByRole("list", { name: "Media" });
    await user.click(screen.getByRole("button", { name: "Select" }));
    await user.click(screen.getByRole("checkbox", { name: /Mine/ }));

    await act(() => router.navigate(`/p/${other.id}/library/all`));

    expect(
      await screen.findByRole("link", { name: /Theirs/ }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Selection" })).toBeNull();
    expect(screen.queryByText("Mine")).toBeNull();
  });
});
