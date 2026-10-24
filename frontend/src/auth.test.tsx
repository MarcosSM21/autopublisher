// Session bootstrap and the global 401 (Feature 020 T022, contracts/ui.md §1).
import { act, cleanup, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { loginPath, safeNext } from "./shell/useAuthSession.ts";
import { FakeApi } from "./test-fake-api.ts";
import { renderRoute } from "./test-utils.tsx";

let api: FakeApi;

beforeEach(() => {
  api = new FakeApi();
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function location(router: ReturnType<typeof renderRoute>["router"]) {
  const { pathname, search } = router.state.location;
  return pathname + search;
}

function privateRequests() {
  return api.requests.filter((request) => !request.path.startsWith("/auth/"));
}

function seed() {
  const project = api.addProject({ name: "Cyber" });
  return { project };
}

describe("session bootstrap", () => {
  it("development renders the app directly, without sign-in", async () => {
    renderRoute("/settings", { api });

    expect(
      await screen.findByRole("navigation", { name: "Main" }),
    ).toBeInTheDocument();
    expect(screen.queryByLabelText("Password")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Sign out" })).toBeNull();
  });

  it("an installation with a session renders the app", async () => {
    api.useInstallation({ authenticated: true });
    const { router } = renderRoute("/settings", { api });

    expect(
      await screen.findByRole("navigation", { name: "Main" }),
    ).toBeInTheDocument();
    expect(location(router)).toBe("/settings");
  });

  it("sends an unauthenticated deep link to /login, with no data request first", async () => {
    api.useInstallation({ authenticated: false });
    const { project } = seed();
    const deepLink = `/p/${project.id}/posts/456?view=week&foo=bar`;
    const { router } = renderRoute(deepLink, { api });

    expect(await screen.findByLabelText("Password")).toBeInTheDocument();
    expect(location(router)).toBe(
      `/login?next=${encodeURIComponent(deepLink)}`,
    );
    expect(privateRequests()).toEqual([]);
    expect(screen.queryByRole("navigation", { name: "Main" })).toBeNull();
    expect(screen.queryByText("Cyber")).toBeNull();
  });

  it("shows nothing of the app while the session is unknown", async () => {
    api.useInstallation({ authenticated: true });
    const release = api.holdRequest("GET", "/auth/session");
    renderRoute("/settings", { api });

    expect(
      await screen.findByText("Loading AutoPublisher…"),
    ).toBeInTheDocument();
    expect(screen.queryByRole("navigation", { name: "Main" })).toBeNull();
    expect(privateRequests()).toEqual([]);
    release();
    expect(
      await screen.findByRole("navigation", { name: "Main" }),
    ).toBeInTheDocument();
  });
});

describe("global 401", () => {
  it("a private request that finds the session gone returns to /login with next", async () => {
    api.useInstallation({ authenticated: true });
    const { project } = seed();
    const { router } = renderRoute("/settings", { api });
    await screen.findByRole("navigation", { name: "Main" });

    api.expireSession();
    const target = `/p/${project.id}/posts?view=week`;
    await act(() => router.navigate(target));

    await waitFor(() =>
      expect(location(router)).toBe(
        `/login?next=${encodeURIComponent(target)}`,
      ),
    );
    expect(await screen.findByLabelText("Password")).toBeInTheDocument();
    // Once on /login, nothing keeps asking for the session in a loop.
    const sessions = api.requests.filter((r) => r.path === "/auth/session");
    expect(sessions.length).toBeLessThanOrEqual(1);
  });

  it.each([
    [
      403,
      "origin_not_allowed",
      "Request blocked: it did not come from AutoPublisher.",
    ],
    [403, "host_not_allowed", "This address is not allowed for AutoPublisher."],
    [409, "host_only_action", "Connect this account from the host."],
    [401, "invalid_credentials", "Incorrect password."],
  ])("a %i %s never signs out", async (status, code, message) => {
    api.useInstallation({ authenticated: true });
    api.failRequest("GET", "/platforms", status, {
      error: { code, message, fields: [] },
    });
    const { router } = renderRoute("/settings", { api });

    expect(await screen.findByRole("alert")).toHaveTextContent(message);
    expect(location(router)).toBe("/settings");
    expect(
      screen.getByRole("navigation", { name: "Main" }),
    ).toBeInTheDocument();
  });
});

describe("next", () => {
  it.each([
    ["/p/1/posts/2?view=week", "/p/1/posts/2?view=week"],
    ["/", "/"],
    [null, "/"],
    ["", "/"],
    ["https://evil.example/", "/"],
    ["//evil.example/path", "/"],
    ["/\\evil.example", "/"],
    ["javascript:alert(1)", "/"],
    ["p/1", "/"],
    ["/login", "/"],
    ["/login?next=/settings", "/"],
    ["/settings\n", "/"],
  ])("safeNext(%j) → %j", (raw, expected) => {
    expect(safeNext(raw)).toBe(expected);
  });

  it("builds the login path from the current location", () => {
    expect(loginPath({ pathname: "/settings", search: "" })).toBe(
      "/login?next=%2Fsettings",
    );
    expect(loginPath({ pathname: "/", search: "" })).toBe("/login");
  });
});
