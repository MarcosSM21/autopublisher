import "@testing-library/jest-dom/vitest";
import { afterEach } from "vitest";
import { resetAuthSession } from "./shell/useAuthSession.ts";

// Each test starts with an unknown session, loaded again from its fake API.
afterEach(() => {
  resetAuthSession();
});
