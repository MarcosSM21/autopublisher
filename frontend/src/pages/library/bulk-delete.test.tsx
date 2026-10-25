import { act, cleanup, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { FakeApi } from "../../test-fake-api.ts";
import { renderRoute } from "../../test-utils.tsx";
import type { Account, LibraryFolderRead, Project } from "../../types.ts";

let api: FakeApi;
let project: Project;
let cyber: LibraryFolderRead;
let youtube: Account;

beforeEach(() => {
  api = new FakeApi();
  api.install();
  project = api.addProject({ name: "L4i4" });
  cyber = api.addFolder({ project_id: project.id, name: "Cyber" });
  youtube = api.addAccount({
    project_id: project.id,
    platform: "youtube",
    handle: "chan",
  });
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const MISSING = "Some selected media no longer exist. Review your selection.";
const IN_PROGRESS =
  "A post using one or more selected media items is being published right now. Try again when it finishes.";
const METADATA_BUSY =
  "Metadata is being removed from one or more selected media items. Try again when it finishes.";

const library = () => `/p/${project.id}/library`;
const deletePath = () => `/projects/${project.id}/contents/delete`;

/** jsdom has no matchMedia: phones by default; this gives a wide screen. */
function setDesktop() {
  vi.stubGlobal(
    "matchMedia",
    (query: string) =>
      ({
        matches: true,
        media: query,
        addEventListener: () => {},
        removeEventListener: () => {},
      }) as unknown as MediaQueryList,
  );
}

async function open(path: string, title: string) {
  const user = userEvent.setup();
  const view = renderRoute(path);
  await screen.findByRole("heading", { level: 1, name: title });
  await screen.findByRole("list", { name: "Media" });
  return { user, ...view };
}

function grid() {
  return screen.getByRole("list", { name: "Media" });
}

/** Behind an open dialog the page is aria-hidden: read the DOM directly. */
function cardsBehind() {
  return document.querySelectorAll(".ap-media-grid > li").length;
}

function countBehind() {
  return document.querySelector(".ap-selection-bar__count")?.textContent;
}

function bar() {
  return screen.getByRole("region", { name: "Selection" });
}

function deleteRequests() {
  return api.requests.filter((request) => request.path === deletePath());
}

function overviewRequests() {
  return api.requests.filter((request) => request.path.startsWith("/overview"))
    .length;
}

/** Select mode, tick `titles`, then the bar's Delete; returns the dialog. */
async function selectAndDelete(
  user: ReturnType<typeof userEvent.setup>,
  titles: string[],
) {
  await user.click(screen.getByRole("button", { name: "Select" }));
  for (const title of titles) {
    await user.click(screen.getByRole("checkbox", { name: new RegExp(title) }));
  }
  await user.click(within(bar()).getByRole("button", { name: "Delete" }));
  const n = titles.length;
  return screen.getByRole("dialog", {
    name: `Delete ${n} media item${n === 1 ? "" : "s"}?`,
  });
}

function media(title: string, folderId: number | null = null) {
  return api.addContent({ project_id: project.id, title, folder_id: folderId });
}

describe("Bulk delete from Select mode", () => {
  it.each([
    ["a folder", () => `${library()}/folders/${cyber.id}`, "Cyber", true],
    ["Unsorted", () => `${library()}/unsorted`, "Unsorted", false],
    ["All media", () => `${library()}/all`, "All media", false],
  ])(
    "in %s deletes every selected media with one confirmation",
    async (_label, view, title, inFolder) => {
      setDesktop();
      const folderId = inFolder ? cyber.id : null;
      const one = media("One", folderId);
      const two = media("Two", folderId);
      media("Kept", folderId);
      api.addPublication({ content_id: one.id, account_id: youtube.id });
      const { user, router } = await open(view(), title);

      await user.click(screen.getByRole("button", { name: "Select" }));
      expect(bar()).toHaveTextContent("0 selected");
      expect(
        within(bar())
          .getAllByRole("button")
          .map((button) => button.textContent),
      ).toEqual(["Move", "Delete", "Cancel"]);
      expect(
        within(bar()).getByRole("button", { name: "Move" }),
      ).toBeDisabled();
      const deleteButton = within(bar()).getByRole("button", {
        name: "Delete",
      });
      expect(deleteButton).toBeDisabled();
      // Destructive text, never the dominant (primary) action.
      expect(deleteButton).toHaveClass(
        "ap-button--secondary",
        "ap-delete-entry",
      );
      expect(within(bar()).getByRole("button", { name: "Move" })).toHaveClass(
        "ap-button--primary",
      );
      await user.click(screen.getByRole("button", { name: "Cancel" }));

      const before = overviewRequests();
      const dialog = await selectAndDelete(user, ["One", "Two"]);
      expect(dialog).toHaveClass("ap-modal--dialog");
      expect(
        await within(dialog).findByText(
          "2 media items and 1 post will be removed from AutoPublisher.",
        ),
      ).toBeInTheDocument();
      // One aggregate: no name line and no list of the selected Media.
      expect(
        dialog.querySelector(".ap-delete-dialog__name"),
      ).not.toBeInTheDocument();
      expect(within(dialog).queryByText("One")).not.toBeInTheDocument();
      expect(within(dialog).queryByRole("textbox")).not.toBeInTheDocument();

      await user.click(within(dialog).getByRole("button", { name: "Delete" }));

      expect(await screen.findByText("2 media deleted.")).toBeInTheDocument();
      expect(deleteRequests().map((request) => request.body)).toEqual([
        {
          content_ids: [one.id, two.id],
          confirmation: expect.stringMatching(/^fake-v1:media_selection:/),
        },
      ]);
      expect(router.state.location.pathname).toBe(view());
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
      expect(screen.queryByRole("region", { name: "Selection" })).toBeNull();
      await vi.waitFor(() =>
        expect(within(grid()).getAllByRole("listitem")).toHaveLength(1),
      );
      expect(within(grid()).getByText("Kept")).toBeInTheDocument();
      expect(api.publications).toHaveLength(0);
      expect(overviewRequests()).toBeGreaterThan(before);

      // Folder, Unsorted and All media counts are read again.
      await act(() => router.navigate(library()));
      const counted = await screen.findByRole("link", {
        name: inFolder ? /Cyber/ : /Unsorted/,
      });
      expect(counted).toHaveTextContent("1 media");
      expect(screen.getByRole("link", { name: /All media/ })).toHaveTextContent(
        "1 media",
      );
    },
  );

  it("shows the view's empty state when nothing is left", async () => {
    media("One");
    media("Two");
    const { user, router } = await open(`${library()}/unsorted`, "Unsorted");
    const dialog = await selectAndDelete(user, ["One", "Two"]);
    await user.click(
      await within(dialog).findByRole("button", { name: "Delete" }),
    );

    expect(
      await screen.findByText("No media without a folder."),
    ).toBeInTheDocument();
    expect(router.state.location.pathname).toBe(`${library()}/unsorted`);
  });

  it("closes the open detail of a deleted media and stays in its list", async () => {
    setDesktop();
    const one = media("One", cyber.id);
    media("Two", cyber.id);
    media("Kept", cyber.id);
    const { user, router } = await open(
      `${library()}/folders/${cyber.id}/${one.id}`,
      "Cyber",
    );
    expect(
      screen.getByRole("button", { name: "Delete media" }),
    ).toBeInTheDocument();

    const dialog = await selectAndDelete(user, ["One", "Two"]);
    await user.click(
      await within(dialog).findByRole("button", { name: "Delete" }),
    );

    expect(await screen.findByText("2 media deleted.")).toBeInTheDocument();
    expect(router.state.location.pathname).toBe(
      `${library()}/folders/${cyber.id}`,
    );
    expect(
      screen.queryByRole("button", { name: "Delete media" }),
    ).not.toBeInTheDocument();
    await vi.waitFor(() =>
      expect(within(grid()).getAllByRole("listitem")).toHaveLength(1),
    );
  });

  it("Cancel in the dialog keeps the selection and deletes nothing", async () => {
    media("One");
    media("Two");
    const { user } = await open(`${library()}/all`, "All media");
    const dialog = await selectAndDelete(user, ["One", "Two"]);
    await user.click(
      await within(dialog).findByRole("button", { name: "Cancel" }),
    );

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(bar()).toHaveTextContent("2 selected");
    expect(deleteRequests()).toHaveLength(0);
    expect(api.contents).toHaveLength(2);
  });
});

describe("A busy media blocks the whole selection", () => {
  it.each([
    ["Remove metadata", false, METADATA_BUSY],
    // Both at once: a publishing post wins.
    ["Remove metadata and Publishing", true, IN_PROGRESS],
  ])(
    "shows the %s blocker with Close only",
    async (_label, publishing, message) => {
      const one = media("One");
      const two = media("Two");
      api.deletionBlockers.set(`media:${one.id}`, {
        code: "metadata_removal_in_progress",
        message: "Metadata is being removed from this media.",
      });
      if (publishing) {
        api.addPublication({
          content_id: two.id,
          account_id: youtube.id,
          status: "publishing",
        });
      }
      const { user } = await open(`${library()}/all`, "All media");
      const dialog = await selectAndDelete(user, ["One", "Two"]);

      expect(await within(dialog).findByText(message)).toBeInTheDocument();
      expect(
        within(dialog).queryByRole("button", { name: "Delete" }),
      ).not.toBeInTheDocument();
      const closes = within(dialog).getAllByRole("button", { name: "Close" });
      await user.click(closes[closes.length - 1]);

      expect(bar()).toHaveTextContent("2 selected");
      expect(deleteRequests()).toHaveLength(0);
      expect(within(grid()).getAllByRole("listitem")).toHaveLength(2);
    },
  );

  it("a delete answering 409 post_in_progress shows the blocker", async () => {
    media("One");
    media("Two");
    const { user } = await open(`${library()}/all`, "All media");
    const dialog = await selectAndDelete(user, ["One", "Two"]);
    api.failRequest("POST", deletePath(), 409, {
      error: { code: "post_in_progress", message: IN_PROGRESS, fields: [] },
    });
    await user.click(
      await within(dialog).findByRole("button", { name: "Delete" }),
    );

    expect(await within(dialog).findByText(IN_PROGRESS)).toBeInTheDocument();
    expect(
      within(dialog).queryByRole("button", { name: "Delete" }),
    ).not.toBeInTheDocument();
    expect(api.contents).toHaveLength(2);
    expect(cardsBehind()).toBe(2);
  });
});

describe("Changes between the confirmation and the delete", () => {
  it("a preview 404 closes the dialog, prunes the selection and deletes nothing", async () => {
    media("One");
    const gone = media("Gone");
    media("Other");
    const { user } = await open(`${library()}/all`, "All media");
    await user.click(screen.getByRole("button", { name: "Select" }));
    await user.click(screen.getByRole("checkbox", { name: /One/ }));
    await user.click(screen.getByRole("checkbox", { name: /Gone/ }));
    // Deleted in another tab.
    api.contents = api.contents.filter((content) => content.id !== gone.id);

    await user.click(within(bar()).getByRole("button", { name: "Delete" }));

    expect(await screen.findByText(MISSING)).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(await screen.findByText("1 selected")).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: /One/ })).toBeChecked();
    expect(screen.queryByRole("checkbox", { name: /Gone/ })).toBeNull();
    expect(deleteRequests()).toHaveLength(0);
    expect(api.contents).toHaveLength(2);
  });

  it("deletion_changed shows the new summary and waits for a second Delete", async () => {
    const one = media("One");
    media("Two");
    const { user } = await open(`${library()}/all`, "All media");
    const dialog = await selectAndDelete(user, ["One", "Two"]);
    const deleteButton = await within(dialog).findByRole("button", {
      name: "Delete",
    });
    expect(dialog).toHaveTextContent(
      "2 media items will be removed from AutoPublisher.",
    );
    // A post is created with one of them in another tab.
    api.addPublication({ content_id: one.id, account_id: youtube.id });

    await user.click(deleteButton);

    expect(
      await within(dialog).findByText("Something changed. Review it again."),
    ).toBeInTheDocument();
    expect(
      await within(dialog).findByText(
        "2 media items and 1 post will be removed from AutoPublisher.",
      ),
    ).toBeInTheDocument();
    expect(api.contents).toHaveLength(2);
    expect(deleteRequests()).toHaveLength(1);
    expect(countBehind()).toBe("2 selected");

    await user.click(within(dialog).getByRole("button", { name: "Delete" }));

    expect(await screen.findByText("2 media deleted.")).toBeInTheDocument();
    expect(deleteRequests()).toHaveLength(2);
    expect(api.contents).toHaveLength(0);
  });

  it("deletion_changed by a vanished media ends in the preview 404 path", async () => {
    media("One");
    const gone = media("Gone");
    const { user } = await open(`${library()}/all`, "All media");
    const dialog = await selectAndDelete(user, ["One", "Gone"]);
    const deleteButton = await within(dialog).findByRole("button", {
      name: "Delete",
    });
    api.contents = api.contents.filter((content) => content.id !== gone.id);

    await user.click(deleteButton);

    expect(await screen.findByText(MISSING)).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(await screen.findByText("1 selected")).toBeInTheDocument();
    expect(deleteRequests()).toHaveLength(1);
    expect(api.contents.map((content) => content.title)).toEqual(["One"]);
  });

  it.each([
    ["a network failure", () => api.failNetworkNext()],
    [
      "a server error",
      () =>
        api.failRequest("POST", deletePath(), 500, {
          error: { code: "internal_error", message: "Boom.", fields: [] },
        }),
    ],
  ])(
    "%s shows the error in the dialog and removes no card",
    async (_label, fail) => {
      media("One");
      media("Two");
      const { user } = await open(`${library()}/all`, "All media");
      const dialog = await selectAndDelete(user, ["One", "Two"]);
      const deleteButton = await within(dialog).findByRole("button", {
        name: "Delete",
      });
      fail();

      await user.click(deleteButton);

      expect(await within(dialog).findByRole("alert")).toHaveTextContent(
        "Couldn't delete it. Try again.",
      );
      expect(cardsBehind()).toBe(2);
      expect(countBehind()).toBe("2 selected");
      expect(api.contents).toHaveLength(2);
    },
  );
});

describe("Bulk delete on a phone", () => {
  it("offers Move, Delete and Cancel and confirms in a sheet", async () => {
    // jsdom has no matchMedia: the phone layout.
    media("One");
    media("Two");
    media("Kept");
    const { user } = await open(`${library()}/all`, "All media");
    await user.click(screen.getByRole("button", { name: "Select" }));
    expect(
      within(bar())
        .getAllByRole("button")
        .map((button) => button.textContent),
    ).toEqual(["Move", "Delete", "Cancel"]);
    await user.click(within(bar()).getByRole("button", { name: "Cancel" }));

    const sheet = await selectAndDelete(user, ["One", "Two"]);

    expect(sheet).toHaveClass("ap-modal--sheet");
    expect(
      await within(sheet).findByText(
        "2 media items will be removed from AutoPublisher.",
      ),
    ).toBeInTheDocument();
    await user.click(within(sheet).getByRole("button", { name: "Delete" }));
    expect(await screen.findByText("2 media deleted.")).toBeInTheDocument();
    await vi.waitFor(() =>
      expect(within(grid()).getAllByRole("listitem")).toHaveLength(1),
    );
  });
});
