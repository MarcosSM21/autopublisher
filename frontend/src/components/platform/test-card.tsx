// Test helper: one platform card in a router (its links) and a task registry.
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import type { FakeApi } from "../../test-fake-api.ts";
import type { Publication } from "../../types.ts";
import AutosaveRegistry from "./AutosaveRegistry.tsx";
import PlatformDetails from "./PlatformDetails.tsx";

export function renderCard(publication: Publication) {
  const user = userEvent.setup();
  render(
    <MemoryRouter>
      <AutosaveRegistry>
        <PlatformDetails publication={publication} />
      </AutosaveRegistry>
    </MemoryRouter>,
  );
  return { user };
}

/** The card's heading region (platform + account). */
export function card(name: RegExp) {
  return screen.getByRole("region", { name });
}

/** Requests that wrote something (PUT/POST/PATCH), by path. */
export function writes(api: FakeApi) {
  return api.requests.filter((request) => request.method !== "GET");
}
