// Test helpers for the Publish task: ready accounts, posts and request logs.
import { vi } from "vitest";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderRoute } from "../../test-utils.tsx";
import type { FakeApi } from "../../test-fake-api.ts";
import {
  platformLabel,
  type Account,
  type AccountHealth,
  type Capability,
  type Platform,
} from "../../types.ts";

const CAPABILITIES: Record<Platform, Capability[]> = {
  youtube: ["videos"],
  instagram: ["images", "videos"],
  threads: ["text", "images", "videos"],
  tiktok: ["videos"],
  telegram: ["text", "images", "videos"],
  x: [],
};

export function health(
  account: Account,
  values: Partial<AccountHealth> = {},
): AccountHealth {
  return {
    account_id: account.id,
    platform: account.platform,
    label: `${platformLabel(account.platform)} @${account.handle}`,
    display_name: null,
    is_active: account.is_active,
    state: account.is_active ? "ready" : "inactive",
    identity: null,
    expires_at: null,
    expiring: false,
    capabilities: CAPABILITIES[account.platform],
    issue: null,
    can_discard: false,
    ...values,
  };
}

/** Every account of the project Ready (unless overridden), in order. */
export function setHealth(
  api: FakeApi,
  projectId: number,
  overrides: Record<number, Partial<AccountHealth>> = {},
) {
  api.accountHealth.set(
    projectId,
    api.accounts
      .filter((account) => account.project_id === projectId)
      .map((account) => health(account, overrides[account.id])),
  );
}

/** Telegram accounts are Ready for publishing as soon as they have a channel. */
export function addTelegram(api: FakeApi, projectId: number, handle: string) {
  const account = api.addAccount({
    project_id: projectId,
    platform: "telegram",
    handle,
  });
  api.setTelegramConnection(account.id);
  return account;
}

export function publishPath(
  projectId: number,
  mediaId: number,
  posts?: number[],
) {
  const base = `/p/${projectId}/library/${mediaId}/publish`;
  return posts === undefined ? base : `${base}?posts=${posts.join(",")}`;
}

export async function openPublish(path: string) {
  const user = userEvent.setup();
  const view = renderRoute(path);
  await screen.findByRole("heading", { level: 1, name: "Publish" });
  return { user, ...view };
}

/** Requests that wrote something (anything but GET). */
export function writes(api: FakeApi) {
  return api.requests.filter((request) => request.method !== "GET");
}

/** The `posts` ids in the router's current URL. */
export function urlPosts(router: { state: { location: { search: string } } }) {
  return new URLSearchParams(router.state.location.search).get("posts");
}

/** Simulates a viewport width for `useMediaQuery` (min-width queries). */
export function setViewport(width: number) {
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
