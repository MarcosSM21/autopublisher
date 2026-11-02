import { cleanup, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import {
  FakeApi,
  PHONE_NOT_CONFIGURED,
  PHONE_SEND_FAILED,
  PHONE_SEND_TIMEOUT,
  TAILSCALE_UNAVAILABLE,
} from "../../test-fake-api.ts";
import { renderRoute } from "../../test-utils.tsx";
import type { Project } from "../../types.ts";

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

async function openDetail() {
  const media = api.addContent({ project_id: project.id, title: "Clip" });
  const user = userEvent.setup();
  renderRoute(`/p/${project.id}/library/all/${media.id}`);
  await screen.findByRole("button", { name: "File details" });
  return { user, media };
}

function sends(contentId: number) {
  return api.requests.filter(
    (r) =>
      r.method === "POST" && r.path === `/contents/${contentId}/send-to-phone`,
  );
}

it("offers one Send to phone button, only in the detail", async () => {
  await openDetail();

  expect(screen.getAllByRole("button", { name: "Send to phone" })).toHaveLength(
    1,
  );
  const grid = screen.getByRole("list", { name: "Media" });
  expect(within(grid).queryByText(/Send to phone/)).toBeNull();
});

it("shows Sending… while the transfer runs, then Sent to phone", async () => {
  const { user, media } = await openDetail();
  const release = api.holdRequest(
    "POST",
    `/contents/${media.id}/send-to-phone`,
  );

  await user.click(screen.getByRole("button", { name: "Send to phone" }));

  const busy = await screen.findByRole("button", { name: /Sending…/ });
  expect(busy).toBeDisabled();
  expect(screen.queryByText("Sent to phone")).toBeNull();
  release();
  expect(await screen.findByText("Sent to phone")).toHaveAttribute(
    "role",
    "status",
  );
  expect(screen.getByRole("button", { name: "Send to phone" })).toBeEnabled();
  expect(sends(media.id)).toHaveLength(1);
});

it.each([
  PHONE_NOT_CONFIGURED,
  TAILSCALE_UNAVAILABLE,
  PHONE_SEND_FAILED,
  PHONE_SEND_TIMEOUT,
])("shows $code and lets the user retry", async (failure) => {
  const { user, media } = await openDetail();
  api.sendToPhoneResult[media.id] = failure;

  await user.click(screen.getByRole("button", { name: "Send to phone" }));

  expect(await screen.findByRole("alert")).toHaveTextContent(failure.message);
  expect(screen.queryByText("Sent to phone")).toBeNull();
  const button = screen.getByRole("button", { name: "Send to phone" });
  expect(button).toBeEnabled();

  delete api.sendToPhoneResult[media.id];
  await user.click(button);

  expect(await screen.findByText("Sent to phone")).toHaveAttribute(
    "role",
    "status",
  );
  expect(screen.queryByRole("alert")).toBeNull();
  expect(sends(media.id)).toHaveLength(2);
});
