// Renders the production route tree in memory (same routes as main.tsx).
import { render } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router";
import { routes } from "./routes.tsx";
import type { FakeApi } from "./test-fake-api.ts";

export function renderRoute(path: string, { api }: { api?: FakeApi } = {}) {
  api?.install();
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  return { router, ...render(<RouterProvider router={router} />) };
}
