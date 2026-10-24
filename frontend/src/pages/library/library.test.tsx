import {
  act,
  cleanup,
  fireEvent,
  screen,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { FakeApi } from "../../test-fake-api.ts";
import { renderRoute } from "../../test-utils.tsx";
import type { Account, Project } from "../../types.ts";

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

function makeFile(name: string, size = 10): File {
  return new File(["x".repeat(size)], name);
}

async function openLibrary(
  path = `/p/${project.id}/library/all`,
  title = "All media",
) {
  // The backend validates formats; the picker filter is only a convenience.
  const user = userEvent.setup({ applyAccept: false });
  const view = renderRoute(path);
  await screen.findByRole("heading", { level: 1, name: title });
  return { user, ...view };
}

function grid() {
  return screen.getByRole("list", { name: "Media" });
}

function cardNames() {
  return within(grid())
    .getAllByRole("link")
    .map((link) => link.querySelector(".ap-media-card__title")?.textContent);
}

function fileInput() {
  return screen.getByLabelText<HTMLInputElement>("Choose files to import");
}

function importRequests() {
  return api.requests.filter(
    (request) =>
      request.method === "POST" && request.path.endsWith("/contents"),
  );
}

describe("Library", () => {
  it("searches by hashtag and filters Not used yet, locally", async () => {
    const youtube = api.addAccount({
      project_id: project.id,
      platform: "youtube",
    });
    api.addContent({
      project_id: project.id,
      title: "Beach",
      hashtags: ["summer"],
    });
    const used = api.addContent({
      project_id: project.id,
      title: "Sunset",
      hashtags: ["summer"],
    });
    api.addContent({ project_id: project.id, title: "Winter" });
    api.addPublication({ content_id: used.id, account_id: youtube.id });
    const { user, router } = await openLibrary();
    await screen.findByRole("list", { name: "Media" });

    await user.type(
      screen.getByRole("searchbox", { name: "Search media" }),
      "#summer",
    );
    expect(cardNames()).toEqual(["Sunset", "Beach"]);

    await user.click(screen.getByRole("radio", { name: "Not used yet" }));
    expect(cardNames()).toEqual(["Beach"]);
    // Search and filters never touch the URL.
    expect(router.state.location.search).toBe("");
    expect(screen.getByText("3 media")).toBeInTheDocument();
  });

  it("shows one usage indicator per card, attention first", async () => {
    const youtube = api.addAccount({
      project_id: project.id,
      platform: "youtube",
    });
    const media = api.addContent({ project_id: project.id, title: "Clip" });
    api.addPublication({ content_id: media.id, account_id: youtube.id });
    api.addPublication({
      content_id: media.id,
      account_id: api.addAccount({ project_id: project.id, platform: "x" }).id,
      status: "failed",
    });
    await openLibrary();

    const card = await screen.findByRole("link", { name: /Clip/ });
    expect(card).toHaveTextContent("1 needs attention");
    expect(card).not.toHaveTextContent("draft");
    expect(card).not.toHaveTextContent("png");
  });

  it("opens the detail beside the kept grid, then returns to the same search and focus", async () => {
    setViewport(1300);
    api.addContent({
      project_id: project.id,
      title: "Beach",
      hashtags: ["summer"],
    });
    api.addContent({
      project_id: project.id,
      title: "Sunset",
      hashtags: ["summer"],
    });
    api.addContent({ project_id: project.id, title: "Winter" });
    const { user, router } = await openLibrary();
    await screen.findByRole("list", { name: "Media" });
    await user.type(
      screen.getByRole("searchbox", { name: "Search media" }),
      "summer",
    );
    await user.click(screen.getByRole("radio", { name: "Not used yet" }));

    const card = screen.getByRole("link", { name: /Sunset/ });
    await user.click(card);
    const panel = await screen.findByRole("complementary", { name: "Sunset" });
    expect(router.state.location.pathname).toMatch(/\/library\/all\/\d+$/);
    expect(screen.getByRole("link", { name: /Sunset/ })).toHaveAttribute(
      "aria-current",
      "true",
    );
    expect(screen.getByRole("link", { name: /Beach/ })).not.toHaveAttribute(
      "aria-current",
    );
    // The detail is a sibling of the grid, never rendered under it.
    expect(grid().parentElement?.contains(panel)).toBe(false);

    await user.click(within(panel).getByRole("button", { name: "Close" }));
    expect(router.state.location.pathname).toBe(`/p/${project.id}/library/all`);
    expect(screen.getByRole("searchbox", { name: "Search media" })).toHaveValue(
      "summer",
    );
    expect(screen.getByRole("radio", { name: "Not used yet" })).toBeChecked();
    expect(screen.getByRole("link", { name: /Sunset/ })).toHaveFocus();
  });

  it("shows the detail as a full page on phones, with the grid kept hidden", async () => {
    const media = api.addContent({ project_id: project.id, title: "Beach" });
    renderRoute(`/p/${project.id}/library/${media.id}`);

    // The page keeps its view's h1 (the older link is the detail over All
    // media); the detail's title is an h2 above its h3s.
    expect(
      await screen.findByRole("heading", { level: 2, name: "Beach" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { level: 1, name: "All media" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("list", { name: "Media" }),
    ).not.toBeInTheDocument();
    expect(document.querySelector(".ap-media-grid")).not.toBeNull();
  });
});

describe("Import", () => {
  it("opens the picker from Import media and reports 2 files with 1 rejected", async () => {
    api.addContent({ project_id: project.id, title: "Existing" });
    const { user } = await openLibrary();
    await screen.findByRole("list", { name: "Media" });
    const click = vi.spyOn(fileInput(), "click");
    await user.click(screen.getByRole("button", { name: "Import media" }));
    expect(click).toHaveBeenCalled();

    await user.upload(fileInput(), [makeFile("a.png"), makeFile("notes.txt")]);

    const panel = await screen.findByRole("region", { name: "Import" });
    expect(
      await within(panel).findByText("1 imported · 0 duplicates · 1 rejected"),
    ).toBeInTheDocument();
    const items = within(
      within(panel).getByRole("list", { name: "Import results" }),
    ).getAllByRole("listitem");
    expect(items[0]).toHaveTextContent("Imported");
    expect(items[0]).toHaveTextContent("a.png");
    expect(items[1]).toHaveTextContent("Rejected");
    expect(items[1]).toHaveTextContent(/Unsupported file format/);
    expect(importRequests().map((request) => request.body)).toEqual([
      { files: ["a.png"] },
      { files: ["notes.txt"] },
    ]);
    // The list is reloaded.
    expect(await within(grid()).findByText("a.png")).toBeInTheDocument();

    await user.click(
      within(panel).getByRole("button", { name: "Dismiss import results" }),
    );
    expect(
      screen.queryByRole("region", { name: "Import" }),
    ).not.toBeInTheDocument();
  });

  it("shows the progress and accepts files dropped on the page from md up", async () => {
    setViewport(800);
    let release: () => void = () => undefined;
    api.importGate = () => new Promise<void>((resolve) => (release = resolve));
    api.addContent({ project_id: project.id, title: "Existing" });
    await openLibrary();
    await screen.findByRole("list", { name: "Media" });

    const page = document.querySelector(".ap-library")!;
    const dataTransfer = {
      files: [makeFile("a.png"), makeFile("b.png")],
      types: ["Files"],
    };
    fireEvent.dragEnter(page, { dataTransfer });
    fireEvent.drop(page, { dataTransfer });

    expect(await screen.findByText("Importing 1 of 2…")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Import media" })).toBeDisabled();
    await act(async () => release());
    expect(await screen.findByText("Importing 2 of 2…")).toBeInTheDocument();
    api.importGate = null;
    await act(async () => release());
    expect(
      await screen.findByText("2 imported · 0 duplicates · 0 rejected"),
    ).toBeInTheDocument();
  });

  it("keeps an empty Library to one primary action, never dependent on dropping", async () => {
    api.projectOverviews.set(project.id, {
      ...api.emptyOverview([project]),
      projects: [
        {
          ...api.emptyOverview([project]).projects[0],
          onboarding: {
            account_ready: true,
            media_imported: false,
            post_created: false,
            complete: false,
          },
        },
      ],
    });
    const { user } = await openLibrary(`/p/${project.id}/library`, "Library");

    const zone = await screen.findByRole("region", { name: "Import media" });
    expect(
      within(zone).getByRole("heading", { name: "Import your first media" }),
    ).toBeInTheDocument();
    expect(
      within(zone).getByText("Choose images or videos from your device."),
    ).toBeInTheDocument();
    const buttons = within(zone).getAllByRole("button");
    expect(buttons).toHaveLength(1);
    await vi.waitFor(() =>
      expect(buttons[0]).toHaveClass("ap-button--primary"),
    );

    // From the root, imports go to Unsorted; the root never shows a grid.
    await user.upload(fileInput(), makeFile("new.png"));
    expect(
      await screen.findByRole("link", { name: /Unsorted\s*1 media/ }),
    ).toBeInTheDocument();
    expect(importRequests().map((request) => request.path)).toEqual([
      `/projects/${project.id}/contents`,
    ]);
    expect(screen.queryByRole("list", { name: "Media" })).toBeNull();
  });

  it("disables importing with its reason when the project is inactive", async () => {
    project.is_active = false;
    await openLibrary(`/p/${project.id}/library`, "Library");

    const zone = await screen.findByRole("region", { name: "Import media" });
    expect(
      within(zone).getByRole("button", { name: "Import media" }),
    ).toBeDisabled();
    expect(
      within(zone).getByText("Reactivate the project to import media."),
    ).toBeInTheDocument();
  });
});

describe("Media detail primary action", () => {
  let youtube: Account;

  beforeEach(() => {
    youtube = api.addAccount({
      project_id: project.id,
      platform: "youtube",
      handle: "chan",
    });
  });

  it("is Publish… without drafts", async () => {
    const media = api.addContent({ project_id: project.id, title: "Fresh" });
    renderRoute(`/p/${project.id}/library/${media.id}`);

    expect(
      await screen.findByRole("link", { name: "Publish…" }),
    ).toHaveAttribute("href", `/p/${project.id}/library/${media.id}/publish`);
  });

  it("continues publishing with the number of drafts and their destinations", async () => {
    const media = api.addContent({ project_id: project.id, title: "Clip" });
    const tiktok = api.addAccount({
      project_id: project.id,
      platform: "tiktok",
      handle: "cyber",
    });
    api.addPublication({ content_id: media.id, account_id: youtube.id });
    api.addPublication({ content_id: media.id, account_id: tiktok.id });
    renderRoute(`/p/${project.id}/library/${media.id}`);

    expect(
      await screen.findByRole("link", {
        name: "Continue publishing · 2 drafts",
      }),
    ).toHaveAttribute("href", `/p/${project.id}/library/${media.id}/publish`);
    expect(
      await screen.findByText("Drafts for TikTok · cyber, YouTube · chan"),
    ).toBeInTheDocument();
  });

  it("is disabled with its reason when the project is inactive", async () => {
    project.is_active = false;
    const media = api.addContent({ project_id: project.id, title: "Fresh" });
    renderRoute(`/p/${project.id}/library/${media.id}`);

    const action = await screen.findByRole("button", { name: "Publish…" });
    expect(action).toBeDisabled();
    expect(action).toHaveAccessibleDescription(
      "Reactivate the project to publish.",
    );
  });

  it("resolves the /publish deep link, and not found for another project's media", async () => {
    const media = api.addContent({ project_id: project.id, title: "Fresh" });
    const { router } = renderRoute(
      `/p/${project.id}/library/${media.id}/publish`,
    );

    expect(
      await screen.findByRole("heading", { level: 1, name: "Publish" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Fresh")).toBeInTheDocument();
    expect(
      await screen.findByRole("group", { name: "Destinations" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Back to media" })).toHaveAttribute(
      "href",
      `/p/${project.id}/library/${media.id}`,
    );
    cleanup();

    const other = api.addContent({
      project_id: api.addProject({ name: "Other" }).id,
    });
    renderRoute(`/p/${project.id}/library/${other.id}/publish`);
    expect(
      await screen.findByRole("heading", { level: 1, name: "Not found" }),
    ).toBeInTheDocument();
    expect(router).toBeDefined();
  });
});

/** The breadcrumb's links and its current (last, unlinked) crumb. */
function expectCrumbs(links: string[], current: string) {
  const crumbs = screen.getByRole("navigation", { name: "Breadcrumb" });
  expect(
    within(crumbs)
      .queryAllByRole("link")
      .map((link) => link.textContent),
  ).toEqual(links);
  expect(crumbs.querySelector('[aria-current="page"]')).toHaveTextContent(
    current,
  );
}

describe("Library root and views", () => {
  function entryNames() {
    return within(screen.getByRole("list", { name: "Library" }))
      .getAllByRole("link")
      .map((link) => link.textContent);
  }

  it("lists top-level folders, Unsorted and All media with counts, never a grid", async () => {
    const cyber = api.addFolder({ project_id: project.id, name: "Cyber" });
    api.addFolder({ project_id: project.id, name: "Art" });
    const child = api.addFolder({
      project_id: project.id,
      name: "DDoS",
      parent_id: cyber.id,
    });
    api.addContent({ project_id: project.id, folder_id: cyber.id });
    api.addContent({ project_id: project.id, folder_id: child.id });
    api.addContent({ project_id: project.id });
    await openLibrary(`/p/${project.id}/library`, "Library");

    await screen.findByRole("list", { name: "Library" });
    // Subfolders live inside their folder, not at the root.
    expect(entryNames()).toEqual([
      "Art0 media",
      "Cyber1 media",
      "Unsorted1 media",
      "All media3 media",
    ]);
    expect(screen.getByRole("link", { name: /^Cyber/ })).toHaveAttribute(
      "href",
      `/p/${project.id}/library/folders/${cyber.id}`,
    );
    expect(screen.queryByRole("list", { name: "Media" })).toBeNull();
    expect(screen.queryByRole("region", { name: "Import media" })).toBeNull();
    expect(
      screen.getByRole("button", { name: "Import media" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "New folder" })).toBeEnabled();
  });

  it("keeps Unsorted, All media and New folder without folders, and the onboarding drop zone without media", async () => {
    await openLibrary(`/p/${project.id}/library`, "Library");

    await screen.findByRole("list", { name: "Library" });
    expect(entryNames()).toEqual(["Unsorted0 media", "All media0 media"]);
    expect(screen.getByRole("button", { name: "New folder" })).toBeEnabled();
    const zone = screen.getByRole("region", { name: "Import media" });
    expect(within(zone).getByRole("button", { name: "Import media" }));
    // One import action: the drop zone's.
    expect(
      screen.getAllByRole("button", { name: "Import media" }),
    ).toHaveLength(1);
    expect(screen.queryByRole("list", { name: "Media" })).toBeNull();
  });

  it("shows a folder's subfolders and only its direct media", async () => {
    const cyber = api.addFolder({ project_id: project.id, name: "Cyber" });
    const child = api.addFolder({
      project_id: project.id,
      name: "DDoS",
      parent_id: cyber.id,
    });
    api.addContent({
      project_id: project.id,
      title: "Own",
      folder_id: cyber.id,
    });
    api.addContent({
      project_id: project.id,
      title: "Deep",
      folder_id: child.id,
    });
    api.addContent({ project_id: project.id, title: "Loose" });
    await openLibrary(`/p/${project.id}/library/folders/${cyber.id}`, "Cyber");

    await screen.findByRole("list", { name: "Media" });
    expect(cardNames()).toEqual(["Own"]);
    const subfolders = screen.getByRole("list", { name: "Folders" });
    expect(within(subfolders).getByRole("link")).toHaveTextContent(
      "DDoS1 media",
    );
    expect(within(subfolders).getByRole("link")).toHaveAttribute(
      "href",
      `/p/${project.id}/library/folders/${child.id}`,
    );
    // The location is obvious here: no folder label on the cards.
    expect(grid()).not.toHaveTextContent("Folder:");
  });

  it("shows only the media without a folder in Unsorted", async () => {
    const cyber = api.addFolder({ project_id: project.id, name: "Cyber" });
    api.addContent({
      project_id: project.id,
      title: "Filed",
      folder_id: cyber.id,
    });
    api.addContent({ project_id: project.id, title: "Loose" });
    await openLibrary(`/p/${project.id}/library/unsorted`, "Unsorted");

    await screen.findByRole("list", { name: "Media" });
    expect(cardNames()).toEqual(["Loose"]);
    expect(screen.queryByRole("list", { name: "Folders" })).toBeNull();
    expectCrumbs(["Library"], "Unsorted");
  });

  it("shows every media in All media, each with its folder", async () => {
    const cyber = api.addFolder({ project_id: project.id, name: "Cyber" });
    api.addContent({
      project_id: project.id,
      title: "Filed",
      folder_id: cyber.id,
    });
    api.addContent({ project_id: project.id, title: "Loose" });
    await openLibrary();

    await screen.findByRole("list", { name: "Media" });
    expect(cardNames()).toEqual(["Loose", "Filed"]);
    expect(screen.getByRole("link", { name: /Loose/ })).toHaveTextContent(
      "Folder: Unsorted",
    );
    expect(screen.getByRole("link", { name: /Filed/ })).toHaveTextContent(
      "Folder: Cyber",
    );
    expectCrumbs(["Library"], "All media");
  });

  it.each([
    ["a folder", "folder", true],
    ["Unsorted", "unsorted", false],
    ["All media", "all", false],
  ])(
    "imports from %s with the right folder_id (never the `folder` filter)",
    async (_label, kind, inFolder) => {
      const cyber = api.addFolder({ project_id: project.id, name: "Cyber" });
      api.addContent({
        project_id: project.id,
        title: "Existing",
        folder_id: inFolder ? cyber.id : null,
      });
      const path = kind === "folder" ? `folders/${cyber.id}` : (kind as string);
      const { user } = await openLibrary(
        `/p/${project.id}/library/${path}`,
        kind === "folder" ? "Cyber" : kind === "all" ? "All media" : "Unsorted",
      );
      await screen.findByRole("list", { name: "Media" });

      await user.upload(fileInput(), makeFile("new.png"));

      expect(await within(grid()).findByText("new.png")).toBeInTheDocument();
      const imports = api.requests.filter(
        (request) =>
          request.method === "POST" && request.path.includes("/contents"),
      );
      expect(imports.map((request) => request.path)).toEqual([
        inFolder
          ? `/projects/${project.id}/contents?folder_id=${cyber.id}`
          : `/projects/${project.id}/contents`,
      ]);
      expect(api.contents.at(-1)?.folder_id).toBe(inFolder ? cyber.id : null);
    },
  );

  it("stops the import and shows Not found when the folder was deleted meanwhile", async () => {
    const cyber = api.addFolder({ project_id: project.id, name: "Cyber" });
    api.addContent({ project_id: project.id, folder_id: cyber.id });
    const { user } = await openLibrary(
      `/p/${project.id}/library/folders/${cyber.id}`,
      "Cyber",
    );
    await screen.findByRole("list", { name: "Media" });
    api.folders = [];
    api.contents[0].folder_id = null;

    await user.upload(fileInput(), makeFile("new.png"));

    expect(
      await screen.findByRole("heading", { level: 1, name: "Not found" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Back to Library" }),
    ).toHaveAttribute("href", `/p/${project.id}/library`);
  });
});
