// The /login page (Feature 020 T023, contracts/ui.md §2).
import { cleanup, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { FakeApi } from "../../test-fake-api.ts";
import { renderRoute } from "../../test-utils.tsx";

let api: FakeApi;

beforeEach(() => {
  api = new FakeApi();
  api.useInstallation({ authenticated: false });
  window.localStorage.clear();
  window.sessionStorage.clear();
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function location(router: ReturnType<typeof renderRoute>["router"]) {
  const { pathname, search } = router.state.location;
  return pathname + search;
}

async function signIn(password: string) {
  const user = userEvent.setup();
  const field = await screen.findByLabelText("Password");
  await user.type(field, password);
  await user.click(screen.getByRole("button", { name: "Sign in" }));
  return field as HTMLInputElement;
}

function loginRequests() {
  return api.requests.filter((request) => request.path === "/auth/login");
}

describe("LoginPage", () => {
  it("is a password-only form outside the app shell, usable on phones", async () => {
    renderRoute("/login", { api });

    const field = await screen.findByLabelText("Password");
    expect(field).toHaveAttribute("type", "password");
    expect(field).toHaveAttribute("autocomplete", "current-password");
    expect(field).toHaveFocus();
    expect(screen.queryByLabelText(/user|email/i)).toBeNull();
    expect(screen.queryByRole("navigation")).toBeNull();
    expect(
      screen.getByText(/Reset it on the computer that runs AutoPublisher/),
    ).toBeInTheDocument();
  });

  it("the branded entrance never delays focus, typing or submit (Feature 026)", async () => {
    renderRoute("/login", { api });

    const form = await screen.findByRole("form", { name: "AutoPublisher" });
    const title = screen.getByRole("heading", { level: 1 });
    expect(title).toHaveAttribute("id", "login-title");
    expect(title.querySelector(".ap-mark")).toHaveAttribute(
      "aria-hidden",
      "true",
    );
    expect(form).toHaveClass("ap-login__card");

    // Focus is in the field on the first render, not after the entrance.
    const field = screen.getByLabelText("Password");
    expect(document.activeElement).toBe(field);

    await userEvent.setup().keyboard(`${api.password}{Enter}`);
    await waitFor(() => expect(loginRequests()).toHaveLength(1));
  });

  it("returns to the original deep link, query included", async () => {
    const project = api.addProject({ name: "Cyber" });
    const deepLink = `/p/${project.id}/posts?view=week&foo=bar`;
    const { router } = renderRoute(
      `/login?next=${encodeURIComponent(deepLink)}`,
      { api },
    );

    await signIn(api.password);

    await waitFor(() => expect(location(router)).toBe(deepLink));
    // The form (and the only copy of the password) is gone with the page.
    expect(screen.queryByLabelText("Password")).toBeNull();
    expect(loginRequests()).toHaveLength(1);
  });

  it("never follows a next outside AutoPublisher", async () => {
    const { router } = renderRoute(
      `/login?next=${encodeURIComponent("//evil.example/x")}`,
      { api },
    );
    await signIn(api.password);
    await waitFor(() => expect(location(router)).toBe("/"));
  });

  it("explains a wrong password and clears the field", async () => {
    const { router } = renderRoute("/login", { api });

    const field = await signIn("not the password");

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Incorrect password.",
    );
    expect(field.value).toBe("");
    expect(location(router)).toBe("/login");
  });

  it("explains the rate limit without technical detail", async () => {
    api.failRequest("POST", "/auth/login", 429, {
      error: {
        code: "too_many_attempts",
        message: "Too many attempts. Try again in a few minutes.",
        fields: [],
      },
    });
    renderRoute("/login", { api });

    await signIn(api.password);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Too many attempts. Try again in a few minutes.",
    );
  });

  it("explains an unreachable server", async () => {
    renderRoute("/login", { api });
    await screen.findByLabelText("Password");
    api.failNetworkNext();

    await signIn(api.password);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Could not reach AutoPublisher",
    );
  });

  it("asks for the password before sending anything", async () => {
    const user = userEvent.setup();
    renderRoute("/login", { api });
    await screen.findByLabelText("Password");

    await user.click(screen.getByRole("button", { name: "Sign in" }));

    expect(screen.getByRole("alert")).toHaveTextContent("Enter the password.");
    expect(loginRequests()).toHaveLength(0);
  });

  it("never keeps the password in storage or the URL", async () => {
    const { router } = renderRoute("/login?next=%2Fsettings", { api });

    await signIn(api.password);
    await waitFor(() => expect(location(router)).toBe("/settings"));

    const stored = [
      ...Object.values({ ...window.localStorage }),
      ...Object.values({ ...window.sessionStorage }),
    ].join("\n");
    expect(stored).not.toContain(api.password);
    expect(location(router)).not.toContain(api.password);
  });

  it("an already signed-in browser skips the form", async () => {
    api.useInstallation({ authenticated: true });
    const { router } = renderRoute("/login", { api });

    await waitFor(() => expect(location(router)).toBe("/"));
  });

  it("development has no sign-in and goes straight to the app", async () => {
    api = new FakeApi(); // development
    const { router } = renderRoute("/login?next=%2Fsettings", { api });

    await waitFor(() => expect(location(router)).toBe("/settings"));
    expect(
      await screen.findByRole("navigation", { name: "Main" }),
    ).toBeInTheDocument();
  });
});
