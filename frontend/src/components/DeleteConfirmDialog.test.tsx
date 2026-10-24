import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../api.ts";
import type { DeletionPreview } from "../types.ts";
import DeleteConfirmDialog, {
  DELETION_CHANGED_MESSAGE,
} from "./DeleteConfirmDialog.tsx";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function preview(overrides: Partial<DeletionPreview> = {}): DeletionPreview {
  return {
    kind: "media",
    id: 42,
    name: "launch-teaser.mp4",
    counts: {
      unpublished_posts: 2,
      remote_posts: 1,
      needs_review_posts: 0,
      accounts: 0,
      posts: 3,
      media: 0,
      subfolders: 0,
      media_to_unsorted: 0,
    },
    summary: [
      "2 unpublished posts and 1 published post will also be removed from AutoPublisher.",
      "Content already published on platforms is not affected.",
    ],
    blocker: null,
    confirmation: "v1:A",
    ...overrides,
  };
}

function conflict(code: string, message = "Busy.") {
  return new ApiError(409, code, message);
}

function setup({
  loadPreview = vi.fn(() => Promise.resolve(preview())),
  remove = vi.fn(() => Promise.resolve()),
}: {
  loadPreview?: () => Promise<DeletionPreview>;
  remove?: (confirmation: string) => Promise<void>;
} = {}) {
  const onDeleted = vi.fn();
  const onClose = vi.fn();
  const user = userEvent.setup();
  render(
    <DeleteConfirmDialog
      title="Delete media?"
      loadPreview={loadPreview}
      remove={remove}
      onDeleted={onDeleted}
      onClose={onClose}
    />,
  );
  const dialog = screen.getByRole("dialog", { name: "Delete media?" });
  return { user, dialog, loadPreview, remove, onDeleted, onClose };
}

describe("DeleteConfirmDialog", () => {
  it("shows a skeleton, then the name and the backend's summary as is", async () => {
    let resolve: (value: DeletionPreview) => void = () => {};
    const { dialog } = setup({
      loadPreview: () => new Promise((done) => (resolve = done)),
    });
    expect(
      within(dialog).getByText("Checking what will be deleted…"),
    ).toBeInTheDocument();
    expect(
      within(dialog).queryByRole("button", { name: "Delete" }),
    ).not.toBeInTheDocument();

    resolve(preview());
    expect(
      await within(dialog).findByText("launch-teaser.mp4"),
    ).toBeInTheDocument();
    for (const line of preview().summary) {
      expect(within(dialog).getByText(line)).toBeInTheDocument();
    }
    // One confirmation: nothing to type, just Delete or Cancel.
    expect(within(dialog).queryByRole("textbox")).not.toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "Delete" })).toHaveClass(
      "ap-button--danger",
    );
  });

  it("deletes with the preview's token on one click", async () => {
    const { user, dialog, remove, onDeleted } = setup();
    await user.click(
      await within(dialog).findByRole("button", { name: "Delete" }),
    );
    expect(remove).toHaveBeenCalledExactlyOnceWith("v1:A");
    expect(onDeleted).toHaveBeenCalledOnce();
  });

  it("cancels without deleting", async () => {
    const { user, dialog, remove, onClose } = setup();
    await user.click(
      await within(dialog).findByRole("button", { name: "Cancel" }),
    );
    expect(onClose).toHaveBeenCalledOnce();
    expect(remove).not.toHaveBeenCalled();
  });

  it("shows a blocker with Close only and never deletes", async () => {
    const { user, dialog, remove, onClose } = setup({
      loadPreview: () =>
        Promise.resolve(
          preview({
            blocker: {
              code: "post_in_progress",
              message:
                "A post using this media is being published right now. Try again when it finishes.",
            },
          }),
        ),
    });
    expect(
      await within(dialog).findByText(
        "A post using this media is being published right now. Try again when it finishes.",
      ),
    ).toBeInTheDocument();
    expect(
      within(dialog).queryByRole("button", { name: "Delete" }),
    ).not.toBeInTheDocument();
    // The footer's Close (the header has its own close icon).
    const closes = within(dialog).getAllByRole("button", { name: "Close" });
    await user.click(closes[closes.length - 1]);
    expect(onClose).toHaveBeenCalled();
    expect(remove).not.toHaveBeenCalled();
  });

  it("on deletion_changed shows the new scope and waits for another Delete", async () => {
    const loadPreview = vi
      .fn<() => Promise<DeletionPreview>>()
      .mockResolvedValueOnce(preview())
      .mockResolvedValueOnce(
        preview({
          summary: [
            "3 unpublished posts and 1 published post will also be removed from AutoPublisher.",
          ],
          confirmation: "v1:B",
        }),
      );
    const remove = vi
      .fn<(confirmation: string) => Promise<void>>()
      .mockRejectedValueOnce(conflict("deletion_changed"))
      .mockResolvedValueOnce(undefined);
    const { user, dialog, onDeleted } = setup({ loadPreview, remove });

    await user.click(
      await within(dialog).findByRole("button", { name: "Delete" }),
    );

    expect(await within(dialog).findByRole("alert")).toHaveTextContent(
      DELETION_CHANGED_MESSAGE,
    );
    expect(
      await within(dialog).findByText(
        "3 unpublished posts and 1 published post will also be removed from AutoPublisher.",
      ),
    ).toBeInTheDocument();
    expect(
      within(dialog).queryByText(preview().summary[0]),
    ).not.toBeInTheDocument();
    // Nothing was deleted on its own with the new scope.
    expect(loadPreview).toHaveBeenCalledTimes(2);
    expect(remove).toHaveBeenCalledTimes(1);
    expect(onDeleted).not.toHaveBeenCalled();

    await user.click(within(dialog).getByRole("button", { name: "Delete" }));
    expect(remove).toHaveBeenLastCalledWith("v1:B");
    expect(onDeleted).toHaveBeenCalledOnce();
  });

  it("treats a 404 on Delete as already deleted, without an error", async () => {
    const { user, dialog, onDeleted } = setup({
      remove: () => Promise.reject(new ApiError(404, "not_found", "Gone.")),
    });
    await user.click(
      await within(dialog).findByRole("button", { name: "Delete" }),
    );
    expect(onDeleted).toHaveBeenCalledOnce();
    expect(within(dialog).queryByRole("alert")).not.toBeInTheDocument();
  });

  it("treats a 404 on the preview as already deleted", async () => {
    const { onDeleted } = setup({
      loadPreview: () =>
        Promise.reject(new ApiError(404, "not_found", "Media not found.")),
    });
    await vi.waitFor(() => expect(onDeleted).toHaveBeenCalledOnce());
  });

  it("shows a 409 busy answer as a blocker with Close only", async () => {
    const { user, dialog, remove } = setup({
      remove: vi.fn(() =>
        Promise.reject(
          conflict(
            "metadata_removal_in_progress",
            "Metadata is being removed from this media. Try again when it finishes.",
          ),
        ),
      ),
    });
    await user.click(
      await within(dialog).findByRole("button", { name: "Delete" }),
    );
    expect(
      await within(dialog).findByText(
        "Metadata is being removed from this media. Try again when it finishes.",
      ),
    ).toBeInTheDocument();
    expect(
      within(dialog).queryByRole("button", { name: "Delete" }),
    ).not.toBeInTheDocument();
    expect(remove).toHaveBeenCalledOnce();
  });

  it("keeps Delete retryable after a generic failure, without technical detail", async () => {
    const remove = vi
      .fn<(confirmation: string) => Promise<void>>()
      .mockRejectedValueOnce(
        new ApiError(500, "internal_error", "IntegrityError: FOREIGN KEY"),
      )
      .mockResolvedValueOnce(undefined);
    const { user, dialog, onDeleted } = setup({ remove });
    await user.click(
      await within(dialog).findByRole("button", { name: "Delete" }),
    );
    const alert = await within(dialog).findByRole("alert");
    expect(alert).toHaveTextContent("Couldn't delete it. Try again.");
    expect(dialog.textContent).not.toMatch(/IntegrityError|internal_error/);

    await user.click(within(dialog).getByRole("button", { name: "Delete" }));
    expect(onDeleted).toHaveBeenCalledOnce();
  });

  it("is a full-screen sheet on phones and a dialog from md", async () => {
    // jsdom has no matchMedia: the mobile-first layout.
    const phone = setup();
    expect(phone.dialog).toHaveClass("ap-modal--sheet");
    expect(
      await within(phone.dialog).findByRole("button", { name: "Delete" }),
    ).toBeVisible();
    expect(
      within(phone.dialog).getByRole("button", { name: "Cancel" }),
    ).toBeVisible();
    cleanup();

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
    expect(setup().dialog).toHaveClass("ap-modal--dialog");
  });
});
