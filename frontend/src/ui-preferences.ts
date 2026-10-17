// The only browser storage AutoPublisher uses: the last project opened, as a
// navigation convenience (research §10). Never business data, never tokens.

const LAST_PROJECT_KEY = "autopublisher.lastProjectId";

/** The last project opened, or null when unknown or storage is unavailable. */
export function getLastProjectId(): number | null {
  try {
    const value = window.localStorage.getItem(LAST_PROJECT_KEY);
    if (value === null || !/^[1-9]\d*$/.test(value)) {
      return null;
    }
    const id = Number(value);
    return Number.isSafeInteger(id) ? id : null;
  } catch {
    return null;
  }
}

export function setLastProjectId(id: number): void {
  if (!Number.isSafeInteger(id) || id <= 0) {
    return;
  }
  try {
    window.localStorage.setItem(LAST_PROJECT_KEY, String(id));
  } catch {
    // Storage unavailable: the app falls back to the first project.
  }
}

export function clearLastProjectId(): void {
  try {
    window.localStorage.removeItem(LAST_PROJECT_KEY);
  } catch {
    // Nothing to clear.
  }
}
