import { cleanup, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { FakeApi } from "./test-fake-api.ts";
import { renderRoute } from "./test-utils.tsx";
import type { Overview, ProjectSummary } from "./types.ts";

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

type Onboarding = ProjectSummary["onboarding"];

/** A project whose (already derived) overview says what the test needs. */
function seed(
  summary: Partial<ProjectSummary> = {},
  automation: Partial<Overview["automation"]> = {},
) {
  const project = api.addProject({ name: "Cyber" });
  const overview = api.emptyOverview([project]);
  Object.assign(overview.projects[0], summary);
  Object.assign(overview.automation, automation);
  api.projectOverviews.set(project.id, overview);
  return project;
}

function onboarding(values: Partial<Onboarding>): Onboarding {
  const steps = {
    account_ready: false,
    media_imported: false,
    post_created: false,
    ...values,
  };
  return {
    ...steps,
    complete: steps.account_ready && steps.media_imported && steps.post_created,
  };
}

function overviewRequests() {
  return api.requests.filter((request) => request.path.startsWith("/overview"));
}

describe("project context", () => {
  it("shows the status strip from one shared overview request", async () => {
    const project = seed(
      {
        accounts_active: 4,
        accounts_ready: 3,
        attention_count: 2,
        next_post: {
          post_id: 7,
          scheduled_at: "2099-01-01T10:00:00Z",
          display_state: "scheduled_automatic",
        },
        onboarding: onboarding({
          account_ready: true,
          media_imported: true,
          post_created: true,
        }),
      },
      { paused: true, paused_automatic_posts: 2 },
    );
    renderRoute(`/p/${project.id}/library`);

    const strip = await screen.findByRole("navigation", {
      name: "Project status",
    });
    const links = within(strip).getAllByRole("link");
    expect(
      links.map((link) => [link.textContent, link.getAttribute("href")]),
    ).toEqual([
      ["3/4 accounts ready", `/p/${project.id}/accounts`],
      ["2 need attention", `/?project=${project.id}`],
      [expect.stringMatching(/^Next: /), `/p/${project.id}/posts/7`],
      ["Automation paused · 2 waiting", "/settings"],
    ]);
    // Complete onboarding: no checklist; no Pause/Resume control in the project.
    expect(
      screen.queryByRole("region", { name: "Get started" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /Pause|Resume/ }),
    ).not.toBeInTheDocument();
    expect(overviewRequests().map((request) => request.path)).toEqual([
      `/overview?project_id=${project.id}`,
    ]);
  });

  it("leaves out empty strip items", async () => {
    const project = seed({ accounts_active: 1, accounts_ready: 1 });
    renderRoute(`/p/${project.id}/library`);

    const strip = await screen.findByRole("navigation", {
      name: "Project status",
    });
    expect(within(strip).getAllByRole("link")).toHaveLength(1);
    expect(strip).toHaveTextContent("1/1 accounts ready");
  });

  it.each([
    [{}, "Connect an account", "accounts/new"],
    [{ account_ready: true }, "Import media", "library"],
    [
      { account_ready: true, media_imported: true },
      "Publish…",
      "library/:media",
    ],
  ])(
    "checklist %j offers only the next step: %s",
    async (steps, action, target) => {
      const project = seed({ onboarding: onboarding(steps) });
      const used = api.addContent({ project_id: project.id, title: "Used" });
      used.usage.used = true;
      const unused = api.addContent({ project_id: project.id, title: "Fresh" });
      renderRoute(`/p/${project.id}/posts`);

      const checklist = await screen.findByRole("region", {
        name: "Get started",
      });
      const items = within(checklist).getAllByRole("listitem");
      expect(items).toHaveLength(3);
      const links = within(checklist).getAllByRole("link");
      expect(links).toHaveLength(1);
      expect(links[0]).toHaveAccessibleName(action);
      const href = `/p/${project.id}/${target.replace(":media", String(unused.id))}`;
      await vi.waitFor(() => expect(links[0]).toHaveAttribute("href", href));
      expect(
        items.filter((item) => item.getAttribute("aria-current") === "step"),
      ).toHaveLength(1);
    },
  );

  it("chooses a Media in All media when every Media is already used", async () => {
    const project = seed({
      onboarding: onboarding({ account_ready: true, media_imported: true }),
    });
    const used = api.addContent({ project_id: project.id, title: "Used" });
    used.usage.used = true;
    renderRoute(`/p/${project.id}/posts`);

    const checklist = await screen.findByRole("region", {
      name: "Get started",
    });
    await vi.waitFor(() =>
      expect(
        within(checklist).getByRole("link", { name: "Publish…" }),
      ).toHaveAttribute("href", `/p/${project.id}/library/all`),
    );
  });

  it("keeps an empty Library to one action that opens the import", async () => {
    const project = seed({ onboarding: onboarding({ account_ready: true }) });
    renderRoute(`/p/${project.id}/library`);

    // The empty state appears once the media list and project context load.
    const zone = await screen.findByRole("region", { name: "Import media" });
    expect(
      within(zone).getByRole("heading", { name: "Import your first media" }),
    ).toBeInTheDocument();
    expect(within(zone).getAllByRole("button")).toHaveLength(1);
    const choose = within(zone).getByRole("button", { name: "Import media" });
    expect(choose).toBeEnabled();
    await waitFor(() => expect(choose).toHaveClass("ap-button--primary"));
  });

  it("keeps importing available but secondary until an account is ready", async () => {
    const project = seed({ onboarding: onboarding({}) });
    renderRoute(`/p/${project.id}/library`);

    const zone = await screen.findByRole("region", { name: "Import media" });
    const choose = within(zone).getByRole("button", { name: "Import media" });
    expect(choose).toBeEnabled();
    expect(choose).toHaveClass("ap-button--secondary");
    const checklist = await screen.findByRole("region", {
      name: "Get started",
    });
    expect(
      within(checklist).getByRole("link", { name: "Connect an account" }),
    ).toHaveClass("ap-button--primary");
  });

  it("keeps empty Posts to one action that opens the Library", async () => {
    const project = seed();
    renderRoute(`/p/${project.id}/posts`);

    const title = await screen.findByRole("heading", { name: "No posts yet" });
    const empty = title.parentElement!;
    const links = within(empty).getAllByRole("link");
    expect(links).toHaveLength(1);
    expect(links[0]).toHaveAccessibleName("Open the Library");
    expect(links[0]).toHaveAttribute("href", `/p/${project.id}/library`);
  });

  it("offers Publish… on an unused media", async () => {
    const project = seed();
    const media = api.addContent({ project_id: project.id, title: "Fresh" });
    renderRoute(`/p/${project.id}/library/${media.id}`);

    expect(
      await screen.findByRole("link", { name: "Publish…" }),
    ).toHaveAttribute("href", `/p/${project.id}/library/${media.id}/publish`);
  });
});

describe("task mode", () => {
  it.each([
    ["Media Publish", "media", "Publish"],
    ["Text Publish", "text", "Text post"],
  ])(
    "%s shows only the task: no bottom navigation, project header, strip or Get started",
    async (_, kind, title) => {
      const project = seed({ accounts_active: 1, accounts_ready: 1 });
      const media = api.addContent({ project_id: project.id, title: "Teaser" });
      renderRoute(
        kind === "media"
          ? `/p/${project.id}/library/${media.id}/publish`
          : `/p/${project.id}/posts/new`,
      );
      await screen.findByRole("heading", { level: 1, name: title });
      await waitFor(() => expect(overviewRequests()).toHaveLength(1));

      expect(screen.queryByRole("navigation", { name: "Main" })).toBeNull();
      expect(
        screen.queryByRole("navigation", { name: "Project status" }),
      ).toBeNull();
      expect(screen.queryByRole("region", { name: "Get started" })).toBeNull();
      expect(
        screen.queryByRole("button", { name: "Project actions" }),
      ).toBeNull();
      // The TopBar (project selector) and the way back stay.
      expect(screen.getByLabelText("Project")).toBeInTheDocument();
      expect(screen.getByRole("link", { name: /^Back/ })).toBeInTheDocument();
    },
  );

  it("normal project pages keep the header, strip and Get started", async () => {
    const project = seed({ accounts_active: 1, accounts_ready: 1 });
    renderRoute(`/p/${project.id}/library`);

    expect(
      await screen.findByRole("navigation", { name: "Project status" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("region", { name: "Get started" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Project actions" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("navigation", { name: "Main" }),
    ).toBeInTheDocument();
  });
});
