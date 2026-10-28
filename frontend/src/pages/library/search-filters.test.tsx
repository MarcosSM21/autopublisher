import { act, cleanup, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { FakeApi } from "../../test-fake-api.ts";
import { renderRoute } from "../../test-utils.tsx";
import type { Account, Content, Project } from "../../types.ts";

let api: FakeApi;
let project: Project;
let youtube: Account;

beforeEach(() => {
  api = new FakeApi();
  api.install();
  project = api.addProject({ name: "L4i4" });
  youtube = api.addAccount({ project_id: project.id, platform: "youtube" });
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

/** jsdom has no matchMedia: answers `(min-width: Npx)` for `width`. */
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

const DAY = 86_400_000;
const all = () => `/p/${project.id}/library/all`;

function daysAgo(days: number): string {
  return new Date(Date.now() - days * DAY).toISOString();
}

function media(values: Partial<Content>): Content {
  return api.addContent({ project_id: project.id, ...values });
}

/** Four Media covering type, usage and age (newest first: café, beach…). */
function fixture() {
  const cafe = media({
    title: "Café de verano",
    media_type: "video",
    created_at: daysAgo(2),
  });
  const beach = media({ title: "Summer beach", created_at: daysAgo(10) });
  api.addPublication({ content_id: beach.id, account_id: youtube.id });
  const winter = media({
    title: "Winter clip",
    media_type: "video",
    created_at: daysAgo(40),
  });
  const notes = media({ title: "a10 notes", created_at: daysAgo(60) });
  return { cafe, beach, winter, notes };
}

async function open(path = all(), title = "All media") {
  const user = userEvent.setup({ applyAccept: false });
  const view = renderRoute(path);
  await screen.findByRole("heading", { level: 1, name: title });
  await screen.findByRole("list", { name: "Media" });
  return { user, ...view };
}

function searchbox() {
  return screen.getByRole("searchbox", { name: "Search media" });
}

function select(name: "Type" | "Usage" | "Imported" | "Sort") {
  return screen.getByRole<HTMLSelectElement>("combobox", { name });
}

function cardNames() {
  const grid = screen.queryByRole("list", { name: "Media" });
  return grid
    ? within(grid)
        .getAllByRole("listitem")
        .map((item) => item.querySelector(".ap-media-card__title")?.textContent)
    : [];
}

function search(router: { state: { location: { search: string } } }) {
  return router.state.location.search;
}

function status() {
  return document.querySelector(".ap-library__query [role='status']")
    ?.textContent;
}

describe("Desktop search, filters and sort in the URL", () => {
  it("filters as the user types, accent-free, with replace", async () => {
    setViewport(1300);
    fixture();
    const { user, router } = await open();

    await user.type(searchbox(), "cafe verano");
    expect(cardNames()).toEqual(["Café de verano"]);
    expect(search(router)).toBe("?q=cafe+verano");
    expect(router.state.historyAction).toBe("REPLACE");
    expect(searchbox()).toHaveValue("cafe verano");
  });

  it("combines Type, Usage and Imported, each in its own param", async () => {
    setViewport(1300);
    fixture();
    const { user, router } = await open();

    await user.selectOptions(select("Type"), "Videos");
    await user.selectOptions(select("Usage"), "Unused");
    expect(cardNames()).toEqual(["Café de verano", "Winter clip"]);
    await user.selectOptions(select("Imported"), "Last 30 days");
    expect(cardNames()).toEqual(["Café de verano"]);
    expect(search(router)).toBe("?type=videos&usage=unused&imported=30d");
    expect(router.state.historyAction).toBe("REPLACE");
  });

  it("sorts by name without changing the set", async () => {
    setViewport(1300);
    fixture();
    const { user, router } = await open();
    expect(cardNames()).toEqual([
      "Café de verano",
      "Summer beach",
      "Winter clip",
      "a10 notes",
    ]);

    await user.selectOptions(select("Sort"), "Name A–Z");
    expect(cardNames()).toEqual([
      "a10 notes",
      "Café de verano",
      "Summer beach",
      "Winter clip",
    ]);
    expect(search(router)).toBe("?sort=name-asc");
  });

  it("restores the search, selects and results from a deep link", async () => {
    setViewport(1300);
    fixture();
    await open(
      `${all()}?q=c&type=videos&usage=unused&imported=90d&sort=oldest`,
    );

    expect(searchbox()).toHaveValue("c");
    expect(select("Type")).toHaveValue("videos");
    expect(select("Usage")).toHaveValue("unused");
    expect(select("Imported")).toHaveValue("90d");
    expect(select("Sort")).toHaveValue("oldest");
    expect(cardNames()).toEqual(["Winter clip", "Café de verano"]);
  });

  it("shows defaults for invalid params, without rewriting the URL", async () => {
    setViewport(1300);
    fixture();
    const { router } = await open(`${all()}?type=gif&sort=size&imported=365`);

    expect(select("Type")).toHaveValue("all");
    expect(select("Imported")).toHaveValue("any");
    expect(select("Sort")).toHaveValue("newest");
    expect(cardNames()).toHaveLength(4);
    expect(search(router)).toBe("?type=gif&sort=size&imported=365");
  });

  it("follows router back and forward between two Library URLs", async () => {
    setViewport(1300);
    fixture();
    const { router } = await open();
    await act(() => router.navigate(`${all()}?type=videos`));
    expect(select("Type")).toHaveValue("videos");
    expect(cardNames()).toEqual(["Café de verano", "Winter clip"]);

    await act(() => router.navigate(-1));
    expect(select("Type")).toHaveValue("all");
    expect(cardNames()).toHaveLength(4);

    await act(() => router.navigate(1));
    expect(select("Type")).toHaveValue("videos");
    expect(cardNames()).toHaveLength(2);
  });

  it("N1: a card link keeps the view and every param", async () => {
    setViewport(1300);
    const { cafe } = fixture();
    await open(`${all()}?q=cafe&type=videos&sort=oldest`);

    expect(
      screen.getByRole("link", { name: /Café de verano/ }),
    ).toHaveAttribute(
      "href",
      `${all()}/${cafe.id}?q=cafe&type=videos&sort=oldest`,
    );
  });

  it("N2: the import panel's link to an existing Media keeps the params", async () => {
    setViewport(1300);
    const { cafe } = fixture();
    const { user } = await open(`${all()}?usage=unused`);

    await user.upload(
      screen.getByLabelText<HTMLInputElement>("Choose files to import"),
      new File(["x".repeat(cafe.size_bytes)], cafe.original_filename),
    );
    const results = await screen.findByRole("list", { name: "Import results" });
    expect(within(results).getByRole("link", { name: "Open" })).toHaveAttribute(
      "href",
      `${all()}/${cafe.id}?usage=unused`,
    );
  });

  it.each([
    ["panel", 1300, "Close"],
    ["drawer", 900, "Close"],
    ["page", 375, "Back"],
  ])(
    "N3: closing the detail (%s) returns to the same params and card",
    async (_mode, width, closeName) => {
      setViewport(width);
      fixture();
      const { user, router } = await open(`${all()}?q=summer&usage=used`);

      await user.click(screen.getByRole("link", { name: /Summer beach/ }));
      await screen.findByRole("heading", { level: 2, name: "Summer beach" });
      expect(search(router)).toBe("?q=summer&usage=used");

      const close = screen.getAllByRole("button", { name: closeName });
      await user.click(close[close.length - 1]);
      expect(router.state.location.pathname).toBe(all());
      expect(search(router)).toBe("?q=summer&usage=used");
      expect(searchbox()).toHaveValue("summer");
      expect(screen.getByRole("link", { name: /Summer beach/ })).toHaveFocus();
    },
  );

  it("N11: the older library/:mediaId link closes to All media with the params", async () => {
    setViewport(1300);
    const { beach } = fixture();
    const { user, router } = await open(
      `/p/${project.id}/library/${beach.id}?q=summer`,
    );

    const panel = await screen.findByRole("complementary", {
      name: "Summer beach",
    });
    await user.click(within(panel).getByRole("button", { name: "Close" }));
    expect(router.state.location.pathname).toBe(all());
    expect(search(router)).toBe("?q=summer");
  });
});

describe("Active filters", () => {
  function chips() {
    return within(screen.getByRole("group", { name: "Active filters" }))
      .getAllByRole("button")
      .map((button) => button.getAttribute("aria-label") ?? button.textContent);
  }

  it("shows one chip per non-default filter, never sort or search", async () => {
    setViewport(1300);
    fixture();
    await open(
      `${all()}?q=c&imported=90d&usage=unused&type=videos&sort=oldest`,
    );

    expect(chips()).toEqual([
      "Remove filter: Videos",
      "Remove filter: Unused",
      "Remove filter: Last 90 days",
      "Clear all",
    ]);
  });

  it("removes one filter at a time, moving focus along the chips", async () => {
    setViewport(1300);
    fixture();
    const { user, router } = await open(
      `${all()}?type=videos&usage=unused&imported=90d`,
    );

    await user.click(
      screen.getByRole("button", { name: "Remove filter: Unused" }),
    );
    expect(search(router)).toBe("?type=videos&imported=90d");
    expect(
      screen.getByRole("button", { name: "Remove filter: Last 90 days" }),
    ).toHaveFocus();

    await user.click(
      screen.getByRole("button", { name: "Remove filter: Last 90 days" }),
    );
    expect(search(router)).toBe("?type=videos");
    expect(
      screen.getByRole("button", { name: "Remove filter: Videos" }),
    ).toHaveFocus();

    await user.click(
      screen.getByRole("button", { name: "Remove filter: Videos" }),
    );
    expect(search(router)).toBe("");
    expect(screen.queryByRole("group", { name: "Active filters" })).toBeNull();
    expect(select("Type")).toHaveFocus();
  });

  it("Clear all keeps the search and the sort", async () => {
    setViewport(1300);
    fixture();
    const { user, router } = await open(
      `${all()}?q=e&type=images&usage=used&sort=name-desc`,
    );

    await user.click(screen.getByRole("button", { name: "Clear all" }));
    expect(search(router)).toBe("?q=e&sort=name-desc");
    expect(select("Type")).toHaveFocus();
  });

  it("Clear search keeps the filters", async () => {
    setViewport(1300);
    fixture();
    const { user, router } = await open(`${all()}?q=winter&type=videos`);

    await user.click(screen.getByRole("button", { name: "Clear search" }));
    expect(search(router)).toBe("?type=videos");
    expect(searchbox()).toHaveValue("");
    expect(screen.queryByRole("button", { name: "Clear search" })).toBeNull();
  });
});

describe("Selection safety", () => {
  /** Three recent, unused images that every change below keeps visible. */
  function items() {
    return ["Item one", "Item two", "Item three"].map((title, index) =>
      media({ title, created_at: daysAgo(index + 1) }),
    );
  }

  function bar() {
    return screen.getByRole("region", { name: "Selection" });
  }

  async function check(
    user: ReturnType<typeof userEvent.setup>,
    titles: string[],
  ) {
    for (const title of titles) {
      await user.click(
        screen.getByRole("checkbox", { name: new RegExp(title) }),
      );
    }
  }

  async function selectAll(user: ReturnType<typeof userEvent.setup>) {
    await user.click(screen.getByRole("button", { name: "Select" }));
    await check(user, ["Item one", "Item two", "Item three"]);
    expect(bar()).toHaveTextContent("3 selected");
  }

  function expectCleared() {
    expect(bar()).toHaveTextContent("0 selected");
    expect(within(bar()).getByRole("button", { name: "Move" })).toBeDisabled();
    expect(
      within(bar()).getByRole("button", { name: "Delete" }),
    ).toBeDisabled();
    expect(screen.getAllByRole("checkbox")).toHaveLength(3);
  }

  type Change = (
    user: ReturnType<typeof userEvent.setup>,
    router: ReturnType<typeof renderRoute>["router"],
  ) => Promise<unknown>;

  it.each<[string, string, Change]>([
    ["typing", "", (user) => user.type(searchbox(), "i")],
    ["Type", "", (user) => user.selectOptions(select("Type"), "Images")],
    ["Usage", "", (user) => user.selectOptions(select("Usage"), "Unused")],
    [
      "Imported",
      "",
      (user) => user.selectOptions(select("Imported"), "Last 7 days"),
    ],
    [
      "removing a chip",
      "?imported=90d",
      (user) =>
        user.click(
          screen.getByRole("button", { name: "Remove filter: Last 90 days" }),
        ),
    ],
    [
      "Clear all",
      "?imported=90d",
      (user) => user.click(screen.getByRole("button", { name: "Clear all" })),
    ],
    [
      "Clear search",
      "?q=item",
      (user) =>
        user.click(screen.getByRole("button", { name: "Clear search" })),
    ],
  ])("%s empties the selection", async (_label, params, change) => {
    setViewport(1300);
    items();
    const { user, router } = await open(all() + params);
    await selectAll(user);

    await change(user, router);
    expectCleared();
  });

  it("router back after a filter change empties the selection", async () => {
    setViewport(1300);
    items();
    const { user, router } = await open();
    await act(() => router.navigate(`${all()}?imported=90d`));
    await selectAll(user);

    await act(() => router.navigate(-1));
    expect(search(router)).toBe("");
    expectCleared();
  });

  it("changing only the sort keeps the selection", async () => {
    setViewport(1300);
    items();
    const { user } = await open();
    await selectAll(user);

    await user.selectOptions(select("Sort"), "Name Z–A");
    expect(bar()).toHaveTextContent("3 selected");
  });

  it("Move and Delete act only on the Media checked after the change", async () => {
    setViewport(1300);
    const [one, two] = items();
    media({ title: "Item video", media_type: "video", created_at: daysAgo(1) });
    const cyber = api.addFolder({ project_id: project.id, name: "Cyber" });
    const { user } = await open();
    await user.click(screen.getByRole("button", { name: "Select" }));
    await check(user, ["Item one", "Item two", "Item three", "Item video"]);

    await user.selectOptions(select("Type"), "Images");
    expectCleared();
    await check(user, ["Item one", "Item two"]);
    expect(bar()).toHaveTextContent("2 selected");

    await user.click(within(bar()).getByRole("button", { name: "Delete" }));
    await screen.findByRole("dialog", { name: "Delete 2 media items?" });
    const previews = api.requests.filter((request) =>
      request.path.endsWith("/contents/deletion-preview"),
    );
    expect(previews.map((request) => request.body)).toEqual([
      { content_ids: [one.id, two.id] },
    ]);
    await user.click(screen.getByRole("button", { name: "Cancel" }));

    await user.click(within(bar()).getByRole("button", { name: "Move" }));
    const picker = screen.getByRole("dialog", { name: "Move 2 media" });
    await user.click(within(picker).getByRole("radio", { name: "Cyber" }));
    await user.click(within(picker).getByRole("button", { name: "Move here" }));
    await screen.findByRole("button", { name: "Select" });
    expect(
      api.requests
        .filter((request) => request.path.endsWith("/move"))
        .map((request) => request.body),
    ).toEqual([{ content_ids: [one.id, two.id], folder_id: cyber.id }]);
  });

  it("never moves a checked Media that stopped matching after a reload", async () => {
    setViewport(1300);
    const [one, two] = items();
    const cyber = api.addFolder({ project_id: project.id, name: "Cyber" });
    const { user } = await open(`${all()}?q=item`);
    await user.click(screen.getByRole("button", { name: "Select" }));
    await check(user, ["Item one", "Item two"]);

    // Edited elsewhere: no longer matches "item" once the view reloads.
    const stored = api.contents.find((content) => content.id === two.id);
    stored!.title = "Renamed";
    await user.upload(
      screen.getByLabelText<HTMLInputElement>("Choose files to import"),
      new File(["x"], "new.png"),
    );
    await screen.findByRole("list", { name: "Import results" });
    expect(bar()).toHaveTextContent("1 selected");

    await user.click(within(bar()).getByRole("button", { name: "Move" }));
    const picker = screen.getByRole("dialog", { name: "Move 1 media" });
    await user.click(within(picker).getByRole("radio", { name: "Cyber" }));
    await user.click(within(picker).getByRole("button", { name: "Move here" }));
    await screen.findByRole("button", { name: "Select" });
    expect(
      api.requests
        .filter((request) => request.path.endsWith("/move"))
        .map((request) => request.body),
    ).toEqual([{ content_ids: [one.id], folder_id: cyber.id }]);
  });

  it("Move keeps the Media checked when it was pressed, whatever the URL does", async () => {
    setViewport(1300);
    const [one, two] = items();
    const cyber = api.addFolder({ project_id: project.id, name: "Cyber" });
    const { user, router } = await open();
    await act(() => router.navigate(`${all()}?imported=90d`));
    await user.click(screen.getByRole("button", { name: "Select" }));
    await check(user, ["Item one", "Item two"]);
    await user.click(within(bar()).getByRole("button", { name: "Move" }));
    expect(screen.getByRole("dialog", { name: "Move 2 media" })).toBeVisible();

    await act(() => router.navigate(-1));
    expect(search(router)).toBe("");
    await act(() => router.navigate(1));
    await act(() => router.navigate(-1));
    const picker = screen.getByRole("dialog", { name: "Move 2 media" });
    await user.click(within(picker).getByRole("radio", { name: "Cyber" }));
    await user.click(within(picker).getByRole("button", { name: "Move here" }));
    await screen.findByRole("button", { name: "Select" });
    expect(
      api.requests
        .filter((request) => request.path.endsWith("/move"))
        .map((request) => request.body),
    ).toEqual([{ content_ids: [one.id, two.id], folder_id: cyber.id }]);
  });

  it("switching to another view resets the selection", async () => {
    setViewport(1300);
    items();
    const { user, router } = await open(
      `/p/${project.id}/library/unsorted`,
      "Unsorted",
    );
    await selectAll(user);

    await act(() => router.navigate(all()));
    await screen.findByRole("heading", { level: 1, name: "All media" });
    expect(screen.queryByRole("region", { name: "Selection" })).toBeNull();
  });
});

describe("Results announcement", () => {
  it("announces the number only with a search or filters, never on sort", async () => {
    setViewport(1300);
    fixture();
    const { user } = await open();
    expect(status()).toBe("");

    await user.type(searchbox(), "summer");
    expect(status()).toBe("1 media");
    await user.selectOptions(select("Type"), "Videos");
    expect(status()).toBe("No media");
    await user.selectOptions(select("Type"), "All");
    await user.clear(searchbox());
    await user.selectOptions(select("Usage"), "Unused");
    expect(status()).toBe("3 media");

    await user.selectOptions(select("Sort"), "Oldest");
    expect(status()).toBe("3 media");
    // The view's own count is unchanged and nothing visible counts results.
    expect(screen.getByText("4 media")).toBeInTheDocument();
  });
});

describe("Navigation context", () => {
  const library = () => `/p/${project.id}/library`;

  function main() {
    return document.querySelector("main")!;
  }

  /** Card titles in the DOM (behind a modal the grid is aria-hidden). */
  function gridTitles() {
    return [
      ...document.querySelectorAll(".ap-media-grid .ap-media-card__title"),
    ].map((title) => title.textContent);
  }

  async function openDetail(path: string, name: string) {
    const user = userEvent.setup();
    const view = renderRoute(path);
    await screen.findByRole("heading", { level: 2, name });
    return { user, ...view };
  }

  async function closeDetail(
    user: ReturnType<typeof userEvent.setup>,
    name: "Close" | "Back",
  ) {
    const buttons = screen.getAllByRole("button", { name });
    await user.click(buttons[buttons.length - 1]);
  }

  /** Focus is somewhere real: the main content or a card still in the grid. */
  function expectSafeFocus() {
    const active = document.activeElement;
    expect(active).not.toBe(document.body);
    expect(active?.isConnected).toBe(true);
    expect(active === main() || active?.matches("[data-detail-id]")).toBe(true);
  }

  async function confirm(
    user: ReturnType<typeof userEvent.setup>,
    title: string,
  ) {
    const dialog = screen.getByRole("dialog", { name: title });
    await user.click(
      await within(dialog).findByRole("button", { name: "Delete" }),
    );
  }

  const SURFACES = [
    ["panel", 1300, "Close"],
    ["drawer", 900, "Close"],
    ["page", 375, "Back"],
  ] as const;

  it("N4: a Media of another view redirects to All media with the params", async () => {
    setViewport(1300);
    const cyber = api.addFolder({ project_id: project.id, name: "Cyber" });
    const clip = media({ title: "Clip", folder_id: cyber.id });
    const { user, router } = await openDetail(
      `${library()}/unsorted/${clip.id}?q=clip&type=images&sort=oldest`,
      "Clip",
    );

    expect(router.state.location.pathname).toBe(`${all()}/${clip.id}`);
    expect(search(router)).toBe("?q=clip&type=images&sort=oldest");
    await closeDetail(user, "Close");
    expect(router.state.location.pathname).toBe(all());
    expect(search(router)).toBe("?q=clip&type=images&sort=oldest");
  });

  it.each(SURFACES)(
    "a deep link to a hidden Media opens it; closing (%s) focuses main",
    async (_surface, width, closeName) => {
      setViewport(width);
      const { beach } = fixture();
      const { user, router } = await openDetail(
        `${all()}/${beach.id}?type=videos`,
        "Summer beach",
      );

      expect(gridTitles()).toEqual(["Café de verano", "Winter clip"]);
      expect(document.querySelector("[aria-current='true']")).toBeNull();
      await closeDetail(user, closeName);
      expect(search(router)).toBe("?type=videos");
      await vi.waitFor(() => expect(main()).toHaveFocus());
    },
  );

  it.each(SURFACES.slice(0, 2))(
    "a Media that stops matching keeps its detail open; closing (%s) focuses main",
    async (_surface, width, closeName) => {
      setViewport(width);
      media({ title: "Summer clip", created_at: daysAgo(1) });
      media({ title: "Summer other", created_at: daysAgo(2) });
      const { user, router } = await open(`${all()}?q=summer`);
      await user.click(screen.getByRole("link", { name: /Summer clip/ }));
      await screen.findByRole("heading", { level: 2, name: "Summer clip" });

      await user.click(screen.getByRole("button", { name: "Edit" }));
      const form = screen.getByRole("form", { name: "Edit content" });
      await user.clear(within(form).getByLabelText("Title"));
      await user.type(within(form).getByLabelText("Title"), "Winter clip");
      await user.click(within(form).getByRole("button", { name: "Save" }));

      expect(
        await screen.findByRole("heading", { level: 2, name: "Winter clip" }),
      ).toBeInTheDocument();
      await vi.waitFor(() => expect(gridTitles()).toEqual(["Summer other"]));
      await closeDetail(user, closeName);
      expect(search(router)).toBe("?q=summer");
      await vi.waitFor(() => expect(main()).toHaveFocus());
    },
  );

  it("N5: moving the open Media out of the view follows it with the params", async () => {
    setViewport(1300);
    const cyber = api.addFolder({ project_id: project.id, name: "Cyber" });
    const clip = media({ title: "Clip" });
    const { user, router } = await openDetail(
      `${library()}/unsorted/${clip.id}?q=clip&sort=name-asc`,
      "Clip",
    );

    const panel = screen.getByRole("complementary", { name: "Clip" });
    await user.click(within(panel).getByRole("button", { name: "Move" }));
    const picker = screen.getByRole("dialog", { name: "Move media" });
    await user.click(within(picker).getByRole("radio", { name: "Cyber" }));
    await user.click(within(picker).getByRole("button", { name: "Move here" }));

    await vi.waitFor(() =>
      expect(router.state.location.pathname).toBe(
        `${library()}/folders/${cyber.id}/${clip.id}`,
      ),
    );
    expect(search(router)).toBe("?q=clip&sort=name-asc");
  });

  it("N6: a bulk Move including the open Media closes it to the view with the params", async () => {
    setViewport(1300);
    api.addFolder({ project_id: project.id, name: "Cyber" });
    const one = media({ title: "Item one" });
    media({ title: "Item two" });
    const { user, router } = await openDetail(
      `${library()}/unsorted/${one.id}?q=item`,
      "Item one",
    );

    await user.click(screen.getByRole("button", { name: "Select" }));
    for (const name of [/Item one/, /Item two/]) {
      await user.click(screen.getByRole("checkbox", { name }));
    }
    const bar = screen.getByRole("region", { name: "Selection" });
    await user.click(within(bar).getByRole("button", { name: "Move" }));
    const picker = screen.getByRole("dialog", { name: "Move 2 media" });
    await user.click(within(picker).getByRole("radio", { name: "Cyber" }));
    await user.click(within(picker).getByRole("button", { name: "Move here" }));

    await vi.waitFor(() =>
      expect(router.state.location.pathname).toBe(`${library()}/unsorted`),
    );
    expect(search(router)).toBe("?q=item");
  });

  it("N7: deleting from the detail keeps the params", async () => {
    setViewport(1300);
    const clip = media({ title: "Clip" });
    media({ title: "Kept" });
    const { user, router } = await openDetail(
      `${library()}/unsorted/${clip.id}?usage=unused`,
      "Clip",
    );

    await user.click(screen.getByRole("button", { name: "Delete media" }));
    await confirm(user, "Delete media?");
    expect(await screen.findByText("Media deleted.")).toBeInTheDocument();
    expect(router.state.location.pathname).toBe(`${library()}/unsorted`);
    expect(search(router)).toBe("?usage=unused");
    await vi.waitFor(() => expect(gridTitles()).toEqual(["Kept"]));
    expectSafeFocus();
  });

  it("N7: deleting from a card menu keeps the params", async () => {
    setViewport(1300);
    media({ title: "Clip" });
    media({ title: "Kept" });
    const { user, router } = await open(
      `${library()}/unsorted?usage=unused`,
      "Unsorted",
    );

    await user.click(
      screen.getByRole("button", { name: "Media actions: Clip" }),
    );
    await user.click(screen.getByRole("button", { name: "Delete media" }));
    await confirm(user, "Delete media?");
    expect(await screen.findByText("Media deleted.")).toBeInTheDocument();
    expect(router.state.location.pathname).toBe(`${library()}/unsorted`);
    expect(search(router)).toBe("?usage=unused");
  });

  it.each([
    ["drawer", 900],
    ["page", 375],
  ])(
    "N7: after deleting from the detail (%s), focus is never on body",
    async (_surface, width) => {
      setViewport(width);
      const clip = media({ title: "Clip" });
      media({ title: "Kept" });
      const { user } = await openDetail(
        `${all()}/${clip.id}?type=images`,
        "Clip",
      );

      await user.click(screen.getByRole("button", { name: "Delete media" }));
      await confirm(user, "Delete media?");
      expect(await screen.findByText("Media deleted.")).toBeInTheDocument();
      await vi.waitFor(() => expect(gridTitles()).toEqual(["Kept"]));
      expect(screen.queryByRole("dialog")).toBeNull();
      await vi.waitFor(() => expectSafeFocus());
      // Once Radix's deferred focus restores have run, too.
      await act(() => new Promise((resolve) => setTimeout(resolve, 0)));
      expectSafeFocus();
    },
  );

  it("N8: a bulk delete keeps the params", async () => {
    setViewport(1300);
    media({ title: "Item one" });
    media({ title: "Item two" });
    media({ title: "Item three" });
    const { user, router } = await open(`${all()}?q=item`);

    await user.click(screen.getByRole("button", { name: "Select" }));
    for (const name of [/Item one/, /Item two/]) {
      await user.click(screen.getByRole("checkbox", { name }));
    }
    const bar = screen.getByRole("region", { name: "Selection" });
    await user.click(within(bar).getByRole("button", { name: "Delete" }));
    await confirm(user, "Delete 2 media items?");
    expect(await screen.findByText("2 media deleted.")).toBeInTheDocument();
    expect(router.state.location.pathname).toBe(all());
    expect(search(router)).toBe("?q=item");
  });

  it("N9: a bulk delete with missing Media keeps the params", async () => {
    setViewport(1300);
    media({ title: "Item one" });
    const gone = media({ title: "Item gone" });
    const { user, router } = await open(`${all()}?q=item`);

    await user.click(screen.getByRole("button", { name: "Select" }));
    for (const name of [/Item one/, /Item gone/]) {
      await user.click(screen.getByRole("checkbox", { name }));
    }
    api.contents = api.contents.filter((content) => content.id !== gone.id);
    const bar = screen.getByRole("region", { name: "Selection" });
    await user.click(within(bar).getByRole("button", { name: "Delete" }));
    expect(
      await screen.findByText(
        "Some selected media no longer exist. Review your selection.",
      ),
    ).toBeInTheDocument();
    expect(router.state.location.pathname).toBe(all());
    expect(search(router)).toBe("?q=item");
  });

  it("N10: deleting a subfolder lands on its parent with the params; a top-level one on the root", async () => {
    setViewport(1300);
    const cyber = api.addFolder({ project_id: project.id, name: "Cyber" });
    const sub = api.addFolder({
      project_id: project.id,
      name: "Sub",
      parent_id: cyber.id,
    });
    const user = userEvent.setup();
    const { router } = renderRoute(
      `${library()}/folders/${sub.id}?q=x&type=videos`,
    );
    await screen.findByRole("heading", { level: 1, name: "Sub" });

    await user.click(screen.getByRole("button", { name: "Folder actions" }));
    await user.click(screen.getByRole("button", { name: "Delete folder" }));
    await confirm(user, "Delete folder?");
    await screen.findByRole("heading", { level: 1, name: "Cyber" });
    expect(router.state.location.pathname).toBe(
      `${library()}/folders/${cyber.id}`,
    );
    expect(search(router)).toBe("?q=x&type=videos");

    await user.click(screen.getByRole("button", { name: "Folder actions" }));
    await user.click(screen.getByRole("button", { name: "Delete folder" }));
    await confirm(user, "Delete folder?");
    await screen.findByRole("heading", { level: 1, name: "Library" });
    expect(router.state.location.pathname).toBe(library());
    expect(search(router)).toBe("");
  });

  it("N12: the detail's Publish link carries the view and the query in from", async () => {
    setViewport(1300);
    const cyber = api.addFolder({ project_id: project.id, name: "Cyber" });
    const clip = media({ title: "Clip", folder_id: cyber.id });
    await openDetail(
      `${library()}/folders/${cyber.id}/${clip.id}?q=cafe+verano&type=videos`,
      "Clip",
    );

    expect(screen.getByRole("link", { name: "Publish…" })).toHaveAttribute(
      "href",
      `${library()}/${clip.id}/publish?from=${encodeURIComponent(
        `folders/${cyber.id}?q=cafe+verano&type=videos`,
      )}`,
    );
  });
});
