import { cleanup, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { FakeApi } from "../test-fake-api.ts";
import type {
  Account,
  AssetPublication,
  Content,
  Project,
  PublicationStatus,
} from "../types.ts";
import { renderRoute } from "../test-utils.tsx";

let api: FakeApi;
let project: Project;
let content: Content;
let youtube: Account;
let instagram: Account;
let x: Account;

beforeEach(() => {
  api = new FakeApi();
  api.install();
  project = api.addProject({ name: "L4i4" });
  content = api.addContent({
    project_id: project.id,
    title: "Summer teaser",
    description: "Content text",
    hashtags: ["summer"],
  });
  youtube = api.addAccount({
    project_id: project.id,
    platform: "youtube",
    handle: "chan",
  });
  instagram = api.addAccount({
    project_id: project.id,
    platform: "instagram",
    handle: "l4i4",
  });
  x = api.addAccount({ project_id: project.id, platform: "x", handle: "l4i4" });
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

async function openDistribute() {
  const user = userEvent.setup();
  renderRoute(`/p/${project.id}/library`);
  await user.click(
    await screen.findByRole("button", { name: /Summer teaser/ }),
  );
  await user.click(screen.getByRole("button", { name: "Publish…" }));
  await screen.findByRole("group", { name: "Destinations" });
  return user;
}

function commonText() {
  return screen.getByRole("group", { name: "Common text" });
}

function destinations() {
  return screen.getByRole("group", { name: "Destinations" });
}

function createBodies() {
  return api.requests
    .filter(
      (request) =>
        request.method === "POST" &&
        request.path === `/contents/${content.id}/publications`,
    )
    .map((request) => request.body);
}

function usage(account: Account, status: PublicationStatus): AssetPublication {
  return {
    publication_id: 900 + account.id,
    platform: account.platform,
    account_id: account.id,
    account_name: `${account.platform} @${account.handle}`,
    status,
    scheduled_at: null,
    published_at: null,
    created_at: "2026-10-05T10:00:00Z",
    updated_at: "2026-10-05T10:00:00Z",
    uncertain: false,
    external_url: null,
  };
}

describe("Distribute", () => {
  it("sends only the edited common text and customized destinations", async () => {
    const user = await openDistribute();
    const create = screen.getByRole("button", {
      name: "Create 0 publications",
    });
    expect(create).toBeDisabled();
    expect(
      screen.getByText("Choose at least one destination."),
    ).toBeInTheDocument();
    await user.click(
      within(destinations()).getByRole("checkbox", { name: /YouTube/ }),
    );
    await user.click(
      within(destinations()).getByRole("checkbox", { name: /Instagram/ }),
    );

    const caption = within(commonText()).getByLabelText(
      "Description / caption",
    );
    expect(caption).toHaveValue("Content text");
    expect(within(commonText()).getByLabelText("Hashtags")).toHaveValue(
      "#summer",
    );
    await user.clear(caption);
    await user.type(caption, "Common caption");

    // YouTube: a custom title; the description still follows the common text.
    const yt = screen.getByRole("group", { name: "YouTube @chan" });
    await user.click(within(yt).getByRole("button", { name: "Customize" }));
    expect(within(yt).getByLabelText("Description / caption")).toHaveValue(
      "Common caption",
    );
    const title = within(yt).getByLabelText("Title");
    expect(title).toHaveValue("Summer teaser");
    await user.clear(title);
    await user.type(title, "YT title");
    expect(within(yt).getByText("Customized")).toBeInTheDocument();

    // Instagram: no title; a customization that is discarded sends nothing.
    const ig = screen.getByRole("group", { name: "Instagram @l4i4" });
    await user.click(within(ig).getByRole("button", { name: "Customize" }));
    expect(within(ig).queryByLabelText("Title")).not.toBeInTheDocument();
    await user.clear(within(ig).getByLabelText("Hashtags"));
    await user.click(
      within(ig).getByRole("button", { name: "Discard customization" }),
    );
    expect(within(ig).queryByText("Customized")).not.toBeInTheDocument();

    await user.click(
      screen.getByRole("button", { name: "Create 2 publications" }),
    );

    expect(createBodies()).toEqual([
      {
        account_ids: [youtube.id, instagram.id],
        description_override: "Common caption",
        targets: { [youtube.id]: { title_override: "YT title" } },
      },
    ]);
    expect(
      await screen.findByText(/Created 2 publications/),
    ).toBeInTheDocument();
  });

  it("schedules with one date and keeps the input when a destination fails", async () => {
    const user = await openDistribute();
    await user.click(
      within(destinations()).getByRole("checkbox", { name: /YouTube/ }),
    );
    await user.click(
      within(destinations()).getByRole("checkbox", { name: /Instagram/ }),
    );
    await user.type(within(commonText()).getByLabelText("Hashtags"), " #extra");
    await user.click(screen.getByRole("radio", { name: "Schedule" }));
    await user.type(screen.getByLabelText("Date and time"), "2100-03-15T18:45");
    api.failNext(422, {
      error: {
        code: "validation_error",
        message: "The request contains invalid data.",
        fields: [
          {
            field: "account_ids",
            message: "Instagram @l4i4 is inactive.",
            account_id: instagram.id,
          },
          {
            field: `targets.${youtube.id}.title_override`,
            message: "Must be at most 200 characters.",
          },
        ],
      },
    });

    await user.click(
      screen.getByRole("button", { name: "Create 2 publications" }),
    );

    expect(createBodies()).toEqual([
      {
        account_ids: [youtube.id, instagram.id],
        hashtags_override: ["#summer", "#extra"],
        scheduled_at: new Date(2100, 2, 15, 18, 45).toISOString(),
      },
    ]);
    expect(
      await within(destinations()).findByText("Instagram @l4i4 is inactive."),
    ).toBeInTheDocument();
    // The Customize panel with the error opens by itself.
    const yt = screen.getByRole("group", { name: "YouTube @chan" });
    expect(
      within(yt).getByText("Must be at most 200 characters."),
    ).toBeInTheDocument();
    expect(within(yt).getByLabelText("Title")).toBeInTheDocument();
    // Everything typed is kept.
    expect(within(commonText()).getByLabelText("Hashtags")).toHaveValue(
      "#summer #extra",
    );
    expect(screen.getByLabelText("Date and time")).toHaveValue(
      "2100-03-15T18:45",
    );
    expect(
      within(destinations()).getByRole("checkbox", { name: /Instagram/ }),
    ).toBeChecked();
  });

  it("only active publications block a destination", async () => {
    api.usageHistory[content.id] = [
      usage(youtube, "published"),
      usage(instagram, "scheduled"),
      usage(x, "cancelled"),
    ];
    const user = await openDistribute();

    const yt = within(destinations()).getByRole("checkbox", {
      name: /YouTube/,
    });
    expect(yt).toBeEnabled();
    expect(
      within(destinations()).getByRole("checkbox", { name: /^X / }),
    ).toBeEnabled();
    expect(
      within(destinations()).getByRole("checkbox", { name: /Instagram/ }),
    ).toBeDisabled();
    expect(
      within(destinations()).getAllByText("Already has an active publication"),
    ).toHaveLength(1);

    await user.click(yt);
    await user.click(
      screen.getByRole("button", { name: "Create 1 publication" }),
    );
    expect(
      await screen.findByText(/Created 1 publication/),
    ).toBeInTheDocument();
  });

  it("shows one compact row per created publication", async () => {
    const telegram = api.addAccount({
      project_id: project.id,
      platform: "telegram",
      handle: "news",
    });
    api.setTelegramConnection(telegram.id);
    const user = await openDistribute();
    await user.click(
      within(destinations()).getByRole("checkbox", { name: /YouTube/ }),
    );
    await user.click(
      within(destinations()).getByRole("checkbox", { name: /Telegram/ }),
    );
    await user.click(
      within(destinations()).getByRole("checkbox", { name: /^X / }),
    );
    await user.click(
      screen.getByRole("button", { name: "Create 3 publications" }),
    );

    const result = await screen.findByRole("region", {
      name: "Distribution result",
    });
    const yt = within(result).getByRole("region", { name: "YouTube @chan" });
    const tg = within(result).getByRole("region", { name: "Telegram @news" });
    expect(await within(yt).findByText("Needs 2")).toBeInTheDocument();
    expect(
      within(yt).getByRole("form", { name: "YouTube options" }),
    ).toBeVisible();
    expect(
      within(yt).getByRole("button", { name: "Publish now" }),
    ).toBeDisabled();
    expect(await within(tg).findByText("Ready")).toBeInTheDocument();
    expect(within(tg).queryByText("Platform options")).not.toBeInTheDocument();
    // A platform without a publisher explains why there is no Publish now.
    const xRow = within(result).getByRole("region", { name: "X @l4i4" });
    expect(
      within(xRow).getByText(
        "Publishing is not available for this platform yet.",
      ),
    ).toBeInTheDocument();
    expect(within(xRow).queryByRole("button")).not.toBeInTheDocument();
    // Compact: no preview, metadata, attempts or schedule form.
    expect(within(result).queryByRole("img")).not.toBeInTheDocument();
    expect(
      within(result).queryByRole("form", { name: "Metadata" }),
    ).not.toBeInTheDocument();
    expect(within(result).queryByText(/Attempts/)).not.toBeInTheDocument();
    expect(
      within(result).queryByRole("button", { name: "Cancel publication" }),
    ).not.toBeInTheDocument();

    await user.click(within(tg).getByRole("button", { name: "Publish now" }));
    expect(within(tg).getByRole("dialog")).toBeInTheDocument();
    expect(within(yt).queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("saves, applies, edits and deletes a destination preset", async () => {
    const user = await openDistribute();
    for (const name of [/YouTube/, /Instagram/, /^X /]) {
      await user.click(within(destinations()).getByRole("checkbox", { name }));
    }
    await user.click(screen.getByText("Manage presets"));
    await user.type(screen.getByLabelText("Preset name"), "Short video");
    await user.click(
      screen.getByRole("button", { name: "Save selection as preset" }),
    );
    expect(
      await screen.findByRole("list", { name: "Presets" }),
    ).toHaveTextContent("Short video 3 destinations");

    // Later: Instagram is deactivated and X gets an active publication.
    api.accounts.find((account) => account.id === instagram.id)!.is_active =
      false;
    api.usageHistory[content.id] = [usage(x, "scheduled")];
    const toggle = screen.getByRole("button", { name: "Publish…" });
    await user.click(toggle);
    await user.click(toggle);
    await screen.findByRole("group", { name: "Destinations" });

    await user.selectOptions(screen.getByLabelText("Preset"), "Short video");

    expect(
      within(destinations()).getByRole("checkbox", { name: /YouTube/ }),
    ).toBeChecked();
    expect(
      within(destinations()).getByRole("checkbox", { name: /^X / }),
    ).not.toBeChecked();
    expect(
      screen.getByText(
        "2 destinations skipped: Instagram @l4i4 (inactive), X @l4i4 (already has an active publication)",
      ),
    ).toBeInTheDocument();
    expect(api.presets[0].account_ids).toEqual(
      [youtube.id, instagram.id, x.id].sort((a, b) => a - b),
    );

    // Edit destinations uses the current selection; rename; delete.
    await user.click(screen.getByText("Manage presets"));
    await user.click(
      screen.getByRole("button", {
        name: "Use the selected destinations for Short video",
      }),
    );
    expect(
      await screen.findByRole("list", { name: "Presets" }),
    ).toHaveTextContent("Short video 1 destination");
    await user.click(
      screen.getByRole("button", { name: "Rename Short video" }),
    );
    const rename = screen.getByLabelText("New name for Short video");
    await user.clear(rename);
    await user.type(rename, "Shorts{Enter}");
    expect(
      await screen.findByRole("button", { name: "Delete Shorts" }),
    ).toBeInTheDocument();
    expect(createBodies()).toEqual([]);
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
    await user.click(screen.getByRole("button", { name: "Delete Shorts" }));
    expect(confirm).toHaveBeenCalledOnce();
    expect(
      screen.queryByRole("list", { name: "Presets" }),
    ).not.toBeInTheDocument();
    expect(api.presets).toEqual([]);
  });
});
