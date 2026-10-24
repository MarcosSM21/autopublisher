const LOOPBACK_HOSTNAMES = new Set(["localhost", "127.0.0.1", "[::1]", "::1"]);

/** The backend's answer when OAuth is started away from the host (api.md §5). */
export const HOST_ONLY_CODE = "host_only_action";

/**
 * Whether this page is open on the computer that runs AutoPublisher through a
 * loopback address: the only place where YouTube and TikTok can redirect back
 * (contracts/ui.md §4). The backend checks it again (`409 host_only_action`).
 */
export function isLoopbackPage(): boolean {
  return LOOPBACK_HOSTNAMES.has(window.location.hostname);
}

/** The loopback address of this same page, for the computer that runs it. */
export function loopbackUrl(): string {
  const { port, pathname, search } = window.location;
  return `http://127.0.0.1${port ? `:${port}` : ""}${pathname}${search}`;
}
