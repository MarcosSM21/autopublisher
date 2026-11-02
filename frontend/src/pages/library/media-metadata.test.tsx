import { cleanup, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import {
  FakeApi,
  METADATA_CHECK_UNAVAILABLE,
  METADATA_NOT_REMOVED,
} from "../../test-fake-api.ts";
import { renderRoute } from "../../test-utils.tsx";
import type { Content, Project } from "../../types.ts";

let api: FakeApi;
let project: Project;

beforeEach(() => {
  api = new FakeApi();
  api.install();
  project = api.addProject({ name: "L4i4" });
  // From xl the detail is a side panel beside the kept grid.
  vi.stubGlobal(
    "matchMedia",
    (query: string) =>
      ({
        matches: 1300 >= Number(/min-width:\s*(\d+)px/.exec(query)?.[1] ?? 0),
        media: query,
        addEventListener: () => {},
        removeEventListener: () => {},
      }) as unknown as MediaQueryList,
  );
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function sanitized(available: boolean): Partial<Content> {
  return {
    metadata_status: "sanitized",
    publish_file: {
      version: "clean_copy",
      available,
      checksum: "clean",
      size_bytes: 900,
      sanitized_at: "2026-10-05T11:00:00Z",
    },
  };
}

async function openDetail(values: Partial<Content> = {}) {
  const media = api.addContent({
    project_id: project.id,
    title: "Clip",
    ...values,
  });
  const user = userEvent.setup();
  renderRoute(`/p/${project.id}/library/all/${media.id}`);
  await screen.findByRole("button", { name: "File details" });
  return { user, media };
}

function metadataRow(): HTMLElement {
  const row = document.querySelector<HTMLElement>(".ap-media-detail__metadata");
  expect(row).not.toBeNull();
  return row!;
}

function card(): HTMLElement {
  return within(screen.getByRole("list", { name: "Media" })).getByRole("link", {
    name: /Clip/,
  });
}

it.each([
  [{}, "Metadata not cleaned", "Not cleaned yet", true],
  [
    { metadata_status: "clean" as const },
    "Metadata cleaned",
    "Already clean",
    false,
  ],
  [sanitized(true), "Metadata cleaned", "Cleaned copy", false],
  [sanitized(false), "Metadata not cleaned", "Clean copy missing", true],
])(
  "shows the metadata state in the header: %o",
  async (values, label, reason, canClean) => {
    await openDetail(values);

    const row = metadataRow();
    expect(row).toHaveTextContent(label);
    expect(row).toHaveTextContent(reason);
    expect(
      within(row).queryByRole("button", { name: "Clean metadata" }) !== null,
    ).toBe(canClean);
  },
);

it("never offers Clean metadata when a clean original's file is missing", async () => {
  await openDetail({
    metadata_status: "clean",
    file_available: false,
    publish_file: {
      version: "original",
      available: false,
      checksum: "c",
      size_bytes: 1000,
      sanitized_at: null,
    },
  });

  expect(metadataRow()).toHaveTextContent("Metadata not cleaned");
  expect(metadataRow()).toHaveTextContent("Media file missing");
  expect(screen.queryByRole("button", { name: "Clean metadata" })).toBeNull();
});

it("cleans from the header and updates the card and the header from the reply", async () => {
  const { user } = await openDetail();
  expect(card()).toHaveAccessibleName(/Metadata not cleaned: Not cleaned yet/);

  await user.click(screen.getByRole("button", { name: "Clean metadata" }));

  expect(await within(metadataRow()).findByText("Cleaned copy")).toBeVisible();
  expect(metadataRow()).toHaveTextContent("Metadata cleaned");
  expect(screen.queryByRole("button", { name: "Clean metadata" })).toBeNull();
  expect(card()).toHaveAccessibleName(/Metadata cleaned: Cleaned copy/);
  expect(
    api.requests.filter((r) => r.path.endsWith("/remove-metadata")),
  ).toHaveLength(1);
});

it("shows Cleaning metadata… while the request is pending", async () => {
  const { user } = await openDetail();
  let release!: () => void;
  const gate = new Promise<void>((resolve) => (release = resolve));
  const fetchBefore = globalThis.fetch;
  vi.stubGlobal("fetch", async (...args: Parameters<typeof fetch>) => {
    if (String(args[0]).endsWith("/remove-metadata")) {
      await gate;
    }
    return fetchBefore(...args);
  });

  await user.click(screen.getByRole("button", { name: "Clean metadata" }));

  expect(
    await screen.findByRole("button", { name: /Cleaning metadata…/ }),
  ).toBeInTheDocument();
  // Nothing turns green before the backend has answered.
  expect(metadataRow()).toHaveTextContent("Metadata not cleaned");
  release();
  expect(await within(metadataRow()).findByText("Cleaned copy")).toBeVisible();
});

it("regenerates a missing clean copy", async () => {
  const { user } = await openDetail(sanitized(false));

  await user.click(screen.getByRole("button", { name: "Clean metadata" }));

  expect(await within(metadataRow()).findByText("Cleaned copy")).toBeVisible();
});

it.each([METADATA_NOT_REMOVED, METADATA_CHECK_UNAVAILABLE])(
  "shows the $code error and keeps the state yellow",
  async (error) => {
    const { user, media } = await openDetail();
    api.removeMetadataResult[media.id] = error;

    await user.click(screen.getByRole("button", { name: "Clean metadata" }));

    expect(await within(metadataRow()).findByRole("alert")).toHaveTextContent(
      error.message,
    );
    expect(metadataRow()).toHaveTextContent("Metadata not cleaned");
    expect(card()).toHaveAccessibleName(/Metadata not cleaned/);
  },
);

it("has exactly one Clean metadata button, even with File details open", async () => {
  const { user } = await openDetail();

  await user.click(screen.getByRole("button", { name: "File details" }));

  expect(
    screen.getAllByRole("button", { name: "Clean metadata" }),
  ).toHaveLength(1);
  expect(
    screen.getByRole("button", { name: "Inspect metadata" }),
  ).toBeVisible();
});
