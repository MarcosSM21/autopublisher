import { useEffect, useSyncExternalStore } from "react";
import { getAuthSession, onAuthRequired, type ApiError } from "../api.ts";
import type { AuthSession } from "../types.ts";
import { toApiError } from "../utils.ts";

/**
 * The sign-in state of this browser (contracts/ui.md §1), loaded once from
 * GET /api/auth/session and shared by the gate, /login and Settings. A plain
 * module store: no state-management framework.
 */
export type AuthState =
  | { status: "loading" }
  | { status: "error"; error: ApiError }
  | { status: "ready"; session: AuthSession };

const SIGNED_OUT: AuthSession = {
  mode: "installation",
  auth_required: true,
  authenticated: false,
};

let state: AuthState = { status: "loading" };
let loading: Promise<void> | null = null;
const listeners = new Set<() => void>();

function publish(next: AuthState) {
  state = next;
  for (const listener of listeners) {
    listener();
  }
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/** (Re)loads the session from the backend; concurrent calls share one request. */
export function loadAuthSession(): Promise<void> {
  loading ??= getAuthSession()
    .then((session) => publish({ status: "ready", session }))
    .catch((caught: unknown) =>
      publish({ status: "error", error: toApiError(caught) }),
    )
    .finally(() => {
      loading = null;
    });
  return loading;
}

export function retryAuthSession(): Promise<void> {
  publish({ status: "loading" });
  return loadAuthSession();
}

/** After a successful login or password change. */
export function markSignedIn(): Promise<void> {
  return loadAuthSession();
}

/** After Sign out, or when a request answered `401 auth_required`. */
export function markSignedOut() {
  publish({ status: "ready", session: SIGNED_OUT });
}

/** Whether this installation asks for a password (never in development). */
export function requiresSignIn(session: AuthSession): boolean {
  return session.auth_required && !session.authenticated;
}

// Any private request that finds the session gone signs this browser out once;
// the gate then leaves the app for /login.
onAuthRequired(() => {
  if (state.status === "ready" && !requiresSignIn(state.session)) {
    markSignedOut();
  }
});

export function useAuthSession(): AuthState {
  const current = useSyncExternalStore(subscribe, () => state);
  useEffect(() => {
    if (state.status === "loading") {
      void loadAuthSession();
    }
  }, []);
  return current;
}

/** Tests only: start every test from an unknown session. */
export function resetAuthSession() {
  state = { status: "loading" };
  loading = null;
}

/**
 * Only internal paths survive the round trip through /login: relative, starting
 * with one "/" (never "//" or "/\" which browsers treat as another host), and
 * never /login itself.
 */
export function safeNext(raw: string | null | undefined): string {
  if (
    !raw ||
    !raw.startsWith("/") ||
    raw.startsWith("//") ||
    raw.includes("\\") ||
    [...raw].some((char) => char.charCodeAt(0) < 0x20) ||
    raw === "/login" ||
    raw.startsWith("/login?") ||
    raw.startsWith("/login/")
  ) {
    return "/";
  }
  return raw;
}

export function loginPath(current: { pathname: string; search: string }) {
  const next = safeNext(current.pathname + current.search);
  return next === "/" ? "/login" : `/login?next=${encodeURIComponent(next)}`;
}
