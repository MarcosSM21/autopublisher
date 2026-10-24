import { afterEach, describe, expect, it, vi } from "vitest";
import {
  ApiError,
  createLibraryFolder,
  deleteObject,
  getDeletionPreview,
  importFile,
  listContents,
  listLibraryFolders,
  moveContents,
  renameLibraryFolder,
  request,
} from "./api.ts";

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
  it("sends JSON bodies with a JSON content type", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, {}));
    vi.stubGlobal("fetch", fetchMock);

    await request("/projects", { method: "POST", body: "{}" });

    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect(init.headers).toEqual({ "Content-Type": "application/json" });
  });

  it("lets the browser set the content type of FormData bodies", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, {}));
    vi.stubGlobal("fetch", fetchMock);

    await request("/projects/1/contents", {
      method: "POST",
      body: new FormData(),
    });

    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect(new Headers(init.headers).has("Content-Type")).toBe(false);
  });

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

describe("Library folders client", () => {
  function stubFetch(body: unknown = {}) {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, body));
    vi.stubGlobal("fetch", fetchMock);
    return () =>
      fetchMock.mock.calls.map(([url, init]) => ({
        url: url as string,
        method: (init as RequestInit | undefined)?.method ?? "GET",
        body: (init as RequestInit | undefined)?.body,
      }));
  }

  it.each([
    [{ kind: "all" } as const, "/api/projects/3/contents"],
    [{ kind: "unsorted" } as const, "/api/projects/3/contents?folder=unsorted"],
    [
      { kind: "folder", folderId: 9 } as const,
      "/api/projects/3/contents?folder=9",
    ],
  ])("lists the %j view with the `folder` filter", async (scope, url) => {
    const calls = stubFetch([]);
    await listContents(3, scope);
    expect(calls()[0].url).toBe(url);
  });

  it("lists All media without any parameter by default", async () => {
    const calls = stubFetch([]);
    await listContents(3);
    expect(calls()[0].url).toBe("/api/projects/3/contents");
  });

  it("imports into a folder with `folder_id`, never with `folder`", async () => {
    const calls = stubFetch({ results: [], summary: {} });
    await importFile(3, new File(["x"], "a.png"), 9);
    await importFile(3, new File(["x"], "b.png"), null);
    await importFile(3, new File(["x"], "c.png"));
    expect(calls().map((call) => call.url)).toEqual([
      "/api/projects/3/contents?folder_id=9",
      "/api/projects/3/contents",
      "/api/projects/3/contents",
    ]);
    expect(calls().every((call) => call.method === "POST")).toBe(true);
  });

  it("creates, renames and lists folders and moves media", async () => {
    const calls = stubFetch();
    await listLibraryFolders(3);
    await createLibraryFolder(3, "DDoS", 7);
    await createLibraryFolder(3, "Top", null);
    await renameLibraryFolder(7, "MFA");
    await moveContents(3, [4, 5], null);
    await moveContents(3, [4], 9);

    expect(
      calls().map(({ url, method, body }) => [
        method,
        url,
        body === undefined ? undefined : JSON.parse(String(body)),
      ]),
    ).toEqual([
      ["GET", "/api/projects/3/library-folders", undefined],
      [
        "POST",
        "/api/projects/3/library-folders",
        { name: "DDoS", parent_id: 7 },
      ],
      [
        "POST",
        "/api/projects/3/library-folders",
        { name: "Top", parent_id: null },
      ],
      ["PATCH", "/api/library-folders/7", { name: "MFA" }],
      [
        "POST",
        "/api/projects/3/contents/move",
        { content_ids: [4, 5], folder_id: null },
      ],
      [
        "POST",
        "/api/projects/3/contents/move",
        { content_ids: [4], folder_id: 9 },
      ],
    ]);
  });
});

describe("Deletion client", () => {
  it.each([
    ["post", "/api/publications/4"],
    ["media", "/api/contents/4"],
    ["account", "/api/accounts/4"],
    ["project", "/api/projects/4"],
    ["folder", "/api/library-folders/4"],
  ] as const)(
    "previews and deletes a %s with the preview's token",
    async (kind, base) => {
      const fetchMock = vi
        .fn()
        .mockResolvedValueOnce(jsonResponse(200, { confirmation: "v1:a+b" }))
        .mockResolvedValueOnce(new Response(null, { status: 204 }));
      vi.stubGlobal("fetch", fetchMock);

      await getDeletionPreview(kind, 4);
      await deleteObject(kind, 4, "v1:a+b");

      const calls = fetchMock.mock.calls.map(([url, init]) => [
        (init as RequestInit | undefined)?.method ?? "GET",
        url as string,
      ]);
      expect(calls).toEqual([
        ["GET", `${base}/deletion-preview`],
        ["DELETE", `${base}?confirmation=v1%3Aa%2Bb`],
      ]);
    },
  );

  it("surfaces deletion_changed as an ApiError with its code", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse(409, {
          error: {
            code: "deletion_changed",
            message: "Something changed since you opened this.",
          },
        }),
      ),
    );
    const error = await captureError(deleteObject("media", 4, "v1:x"));
    expect([error.status, error.code]).toEqual([409, "deletion_changed"]);
  });
});
