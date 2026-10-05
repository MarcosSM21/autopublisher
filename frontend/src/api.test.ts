import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, request } from "./api.ts";

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

async function captureError(promise: Promise<unknown>): Promise<ApiError> {
  try {
    await promise;
  } catch (error) {
    if (error instanceof ApiError) {
      return error;
    }
    throw error;
  }
  throw new Error("Expected the request to fail");
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("request", () => {
  it("returns the parsed body of a successful response", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(jsonResponse(200, [{ id: 1 }])),
    );

    await expect(request("/projects")).resolves.toEqual([{ id: 1 }]);
    expect(fetch).toHaveBeenCalledWith("/api/projects", expect.anything());
  });

  it("turns an error body into an ApiError", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse(409, {
          error: {
            code: "duplicate",
            message: "A project with this name already exists.",
            fields: [{ field: "name", message: "Already in use." }],
          },
        }),
      ),
    );

    const error = await captureError(request("/projects"));

    expect(error.status).toBe(409);
    expect(error.code).toBe("duplicate");
    expect(error.message).toBe("A project with this name already exists.");
    expect(error.fieldMessage("name")).toBe("Already in use.");
  });

  it("keeps the server message of an internal error", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse(500, {
          error: {
            code: "internal_error",
            message: "An unexpected error occurred. Please try again.",
            fields: [],
          },
        }),
      ),
    );

    const error = await captureError(request("/projects"));

    expect(error.code).toBe("internal_error");
    expect(error.message).toBe(
      "An unexpected error occurred. Please try again.",
    );
  });

  it("reports a response without the error format as unexpected", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response("Bad Gateway", { status: 502 })),
    );

    const error = await captureError(request("/projects"));

    expect(error.status).toBe(502);
    expect(error.code).toBe("unexpected_error");
  });

  it("reports a failed fetch as a network error", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("failed")));

    const error = await captureError(request("/projects"));

    expect(error.code).toBe("network_error");
    expect(error.message).toBe("Could not reach the server.");
  });
});
