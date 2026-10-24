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

const library = () => `/p/${project.id}/library`;

/** A Library view, once its grid is shown. */
async function open(path: string, title: string) {
  const user = userEvent.setup();
  const view = renderRoute(path);
  await screen.findByRole("heading", { level: 1, name: title });
  await screen.findByRole("list", { name: "Media" });
  return { user, ...view };
}

/** A Media detail (a full page on phones, the default here). */
async function openDetail(path: string) {
  const user = userEvent.setup();
  const view = renderRoute(path);
  await screen.findByRole("button", { name: "Delete media" });
  return { user, ...view };
}

function grid() {
  return screen.getByRole("list", { name: "Media" });
}

async function confirmDelete(user: ReturnType<typeof userEvent.setup>) {
  const dialog = screen.getByRole("dialog", { name: "Delete media?" });
  await user.click(
    await within(dialog).findByRole("button", { name: "Delete" }),
  );
}

describe("Delete media", () => {
  it("shows the dependent Posts exactly as the backend summarises them", async () => {
    const media = api.addContent({ project_id: project.id, title: "Clip" });
    api.addPublication({ content_id: media.id, account_id: youtube.id });
    const published = api.addPublication({
      content_id: media.id,
      account_id: youtube.id,
    });
    api.startAttempt(api.publications.find((r) => r.id === published.id)!);
    api.succeedAttempt(published.id);
    const { user } = await openDetail(`${library()}/all/${media.id}`);

    await user.click(screen.getByRole("button", { name: "Delete media" }));
    const dialog = screen.getByRole("dialog", { name: "Delete media?" });
    expect(
      await within(dialog).findByText(
        "1 unpublished post and 1 published post will also be removed from AutoPublisher.",
      ),
    ).toBeInTheDocument();
    expect(dialog).toHaveTextContent(
      "Content already published on platforms is not affected.",
    );
  });

  it.each([
    ["a folder", () => `${library()}/folders/${cyber.id}`, () => "Cyber"],
    ["Unsorted", () => `${library()}/unsorted`, () => "Unsorted"],
    ["All media", () => `${library()}/all`, () => "All media"],
  ])(
    "from the detail in %s → back to that view, without the card",
    async (_label, view, title) => {
      const folderId = title() === "Cyber" ? cyber.id : null;
      const media = api.addContent({
        project_id: project.id,
        title: "Clip",
        folder_id: folderId,
      });
      api.addContent({
        project_id: project.id,
        title: "Kept",
        folder_id: folderId,
      });
      const { user, router } = await openDetail(`${view()}/${media.id}`);

      await user.click(screen.getByRole("button", { name: "Delete media" }));
      await confirmDelete(user);

      expect(router.state.location.pathname).toBe(view());
      expect(await screen.findByText("Media deleted.")).toBeInTheDocument();
      await vi.waitFor(() =>
        expect(within(grid()).getAllByRole("listitem")).toHaveLength(1),
      );
      expect(within(grid()).getByText("Kept")).toBeInTheDocument();
      expect(screen.queryByText("Clip")).not.toBeInTheDocument();
    },
  );

  it("from the older detail link → All media", async () => {
    const media = api.addContent({ project_id: project.id, title: "Clip" });
    const { user, router } = await openDetail(`${library()}/${media.id}`);
    await user.click(screen.getByRole("button", { name: "Delete media" }));
    await confirmDelete(user);
    expect(router.state.location.pathname).toBe(`${library()}/all`);
    expect(
      await screen.findByRole("heading", { level: 1, name: "All media" }),
    ).toBeInTheDocument();
  });

  it("the card's Media actions offer Move and Delete media, tap to open", async () => {
    const media = api.addContent({
      project_id: project.id,
      title: "Clip",
      folder_id: cyber.id,
    });
    const { user } = await open(`${library()}/folders/${cyber.id}`, "Cyber");
    const toggle = within(grid()).getByRole("button", {
      name: "Media actions: Clip",
    });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    await user.click(toggle);
    const card = toggle.closest("li")!;
    expect(
      within(card)
        .getAllByRole("button")
        .map((button) => button.textContent),
    ).toEqual(["Media actions: Clip", "Move", "Delete media"]);

    // Move from the card: the media leaves this folder.
    await user.click(within(card).getByRole("button", { name: "Move" }));
    const picker = screen.getByRole("dialog", { name: "Move media" });
    await user.click(within(picker).getByRole("radio", { name: /Unsorted/ }));
    await user.click(within(picker).getByRole("button", { name: "Move here" }));
    expect(
      await screen.findByText("No media in this folder yet."),
    ).toBeInTheDocument();
    expect(api.contents.find((c) => c.id === media.id)?.folder_id).toBeNull();
  });

  it("deletes from the card menu, stays in the view and updates the counts", async () => {
    api.addContent({ project_id: project.id, title: "Clip" });
    api.addContent({ project_id: project.id, title: "Kept" });
    const { user, router } = await open(`${library()}/unsorted`, "Unsorted");

    await user.click(
      within(grid()).getByRole("button", { name: "Media actions: Clip" }),
    );
    await user.click(
      within(grid()).getByRole("button", { name: "Delete media" }),
    );
    await confirmDelete(user);

    expect(router.state.location.pathname).toBe(`${library()}/unsorted`);
    expect(await screen.findByText("Media deleted.")).toBeInTheDocument();
    await vi.waitFor(() =>
      expect(within(grid()).queryByText("Clip")).not.toBeInTheDocument(),
    );
    expect(within(grid()).getAllByRole("listitem")).toHaveLength(1);

    // The Library root counts it no more.
    await act(() => router.navigate(library()));
    const unsorted = await screen.findByRole("link", { name: /Unsorted/ });
    expect(unsorted).toHaveTextContent("1 media");
    expect(screen.getByRole("link", { name: /All media/ })).toHaveTextContent(
      "1 media",
    );
  });

  it("offers no card menu in Select mode", async () => {
    api.addContent({ project_id: project.id, title: "Clip" });
    const { user } = await open(`${library()}/all`, "All media");
    await user.click(screen.getByRole("button", { name: "Select" }));
    expect(
      screen.queryByRole("button", { name: /Media actions/ }),
    ).not.toBeInTheDocument();
  });
});
