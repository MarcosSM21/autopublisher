// In-memory stand-in for the backend API used by UI tests (see contracts/api.md).
import { vi } from "vitest";
import type {
  Account,
  Content,
  ImportItemResult,
  MediaFormat,
  Project,
} from "./types.ts";

type FailureResponse = { status: number; body: unknown } | { network: true };

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function errorBody(
  code: string,
  message: string,
  fields: { field: string; message: string }[] = [],
) {
  return { error: { code, message, fields } };
}

const TIMESTAMP = "2026-10-05T10:00:00Z";
const LATER = "2026-10-05T11:00:00Z";

export class FakeApi {
  projects: Project[] = [];
  accounts: Account[] = [];
  contents: Content[] = [];
  requests: { method: string; path: string; body: unknown }[] = [];
  /** When set, each import request waits for it before answering. */
  importGate: (() => Promise<void>) | null = null;
  private nextId = 1;
  private failures: FailureResponse[] = [];

  addProject(values: Partial<Project> & { name: string }): Project {
    const project: Project = {
      id: this.nextId++,
      description: null,
      is_active: true,
      created_at: TIMESTAMP,
      updated_at: TIMESTAMP,
      ...values,
    };
    this.projects.push(project);
    return project;
  }

  addAccount(
    values: Partial<Account> & Pick<Account, "project_id" | "platform">,
  ): Account {
    const account: Account = {
      id: this.nextId++,
      handle: "handle",
      display_name: null,
      is_active: true,
      created_at: TIMESTAMP,
      updated_at: TIMESTAMP,
      ...values,
    };
    this.accounts.push(account);
    return account;
  }

  addContent(values: Partial<Content> & Pick<Content, "project_id">): Content {
    const id = this.nextId++;
    const content: Content = {
      id,
      media_type: "image",
      media_format: "png",
      original_filename: `file-${id}.png`,
      title: null,
      description: null,
      hashtags: [],
      checksum: `checksum-${id}`,
      size_bytes: 1000,
      width: 8,
      height: 6,
      duration_seconds: null,
      file_url: `/api/contents/${id}/file`,
      file_available: true,
      created_at: TIMESTAMP,
      updated_at: TIMESTAMP,
      ...values,
    };
    this.contents.push(content);
    return content;
  }

  failNext(status: number, body: unknown): void {
    this.failures.push({ status, body });
  }

  failNetworkNext(): void {
    this.failures.push({ network: true });
  }

  install(): void {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: string, init?: RequestInit) => {
        const isImport =
          init?.method === "POST" && init.body instanceof FormData;
        if (isImport && this.importGate) {
          await this.importGate();
        }
        return this.handle(input, init);
      }),
    );
  }

  /** Simplified import rules: see tasks.md T015. */
  private importFile(projectId: number, file: File): ImportItemResult {
    const base = {
      filename: file.name,
      content: null,
      existing_content: null,
      error: null,
    };
    const format = formatFromName(file.name);
    if (format === null) {
      return {
        ...base,
        status: "rejected",
        error: {
          code: "unsupported_format",
          message:
            "Unsupported file format. Supported: JPEG, PNG, WebP, MP4, MOV, WebM.",
        },
      };
    }
    if (file.size === 0) {
      return {
        ...base,
        status: "rejected",
        error: { code: "empty_file", message: "The file is empty." },
      };
    }
    const existing = this.contents.find(
      (content) =>
        content.project_id === projectId &&
        content.original_filename === file.name &&
        content.size_bytes === file.size,
    );
    if (existing) {
      return { ...base, status: "duplicate", existing_content: existing };
    }
    const content = this.addContent({
      project_id: projectId,
      original_filename: file.name,
      size_bytes: file.size,
      media_format: format,
      media_type: VIDEO_FORMATS.includes(format) ? "video" : "image",
      created_at: LATER,
      updated_at: LATER,
    });
    return { ...base, status: "imported", content };
  }

  private handle(url: string, init?: RequestInit): Response {
    const method = init?.method ?? "GET";
    const path = url.replace(/^\/api/, "");
    const form = init?.body instanceof FormData ? init.body : null;
    const body: unknown = form
      ? { files: form.getAll("files").map((file) => (file as File).name) }
      : init?.body
        ? JSON.parse(String(init.body))
        : null;
    this.requests.push({ method, path, body });

    const failure = method === "GET" ? undefined : this.failures.shift();
    if (failure) {
      if ("network" in failure) {
        throw new TypeError("Failed to fetch");
      }
      return json(failure.status, failure.body);
    }

    let match: RegExpMatchArray | null;
    if (path === "/projects" && method === "GET") {
      const sorted = [...this.projects].sort((a, b) =>
        a.name.toLowerCase().localeCompare(b.name.toLowerCase()),
      );
      return json(200, sorted);
    }
    if (path === "/projects" && method === "POST") {
      const { name, description } = body as {
        name: string;
        description: string | null;
      };
      return json(
        201,
        this.addProject({
          name: name.trim(),
          description: description || null,
        }),
      );
    }
    if ((match = path.match(/^\/projects\/(\d+)$/))) {
      const project = this.projects.find((p) => p.id === Number(match![1]));
      if (!project) {
        return json(404, errorBody("not_found", "Project not found."));
      }
      if (method === "PATCH") {
        Object.assign(project, body, { updated_at: LATER });
      }
      return json(200, project);
    }
    if ((match = path.match(/^\/projects\/(\d+)\/accounts$/))) {
      const projectId = Number(match[1]);
      const project = this.projects.find((p) => p.id === projectId);
      if (!project) {
        return json(404, errorBody("not_found", "Project not found."));
      }
      if (method === "POST") {
        if (!project.is_active) {
          return json(
            409,
            errorBody(
              "project_inactive",
              "Reactivate the project before adding accounts.",
            ),
          );
        }
        const values = body as Pick<
          Account,
          "platform" | "handle" | "display_name"
        >;
        return json(
          201,
          this.addAccount({
            project_id: projectId,
            platform: values.platform,
            handle: values.handle.trim().replace(/^@/, ""),
            display_name: values.display_name || null,
          }),
        );
      }
      return json(
        200,
        this.accounts.filter((account) => account.project_id === projectId),
      );
    }
    if ((match = path.match(/^\/projects\/(\d+)\/contents$/))) {
      const projectId = Number(match[1]);
      const project = this.projects.find((p) => p.id === projectId);
      if (!project) {
        return json(404, errorBody("not_found", "Project not found."));
      }
      if (method === "POST" && form) {
        if (!project.is_active) {
          return json(
            409,
            errorBody(
              "project_inactive",
              "Reactivate the project before importing content.",
            ),
          );
        }
        const files = form.getAll("files") as File[];
        const results = files.map((file) => this.importFile(projectId, file));
        return json(200, {
          results,
          summary: {
            imported: results.filter((r) => r.status === "imported").length,
            duplicates: results.filter((r) => r.status === "duplicate").length,
            rejected: results.filter((r) => r.status === "rejected").length,
          },
        });
      }
      const contents = this.contents
        .filter((content) => content.project_id === projectId)
        .sort((a, b) => b.id - a.id);
      return json(200, contents);
    }
    if ((match = path.match(/^\/contents\/(\d+)$/))) {
      const content = this.contents.find((c) => c.id === Number(match![1]));
      if (!content) {
        return json(404, errorBody("not_found", "Content not found."));
      }
      if (method === "PATCH") {
        const patch = { ...(body as Partial<Content>) };
        if (patch.hashtags) {
          patch.hashtags = patch.hashtags.map((tag) => tag.replace(/^#/, ""));
        }
        const changed = Object.entries(patch).some(
          ([key, value]) =>
            JSON.stringify(content[key as keyof Content]) !==
            JSON.stringify(value),
        );
        Object.assign(content, patch, changed ? { updated_at: LATER } : {});
      }
      return json(200, content);
    }
    if ((match = path.match(/^\/accounts\/(\d+)$/)) && method === "PATCH") {
      const account = this.accounts.find((a) => a.id === Number(match![1]));
      if (!account) {
        return json(404, errorBody("not_found", "Account not found."));
      }
      const patch = { ...(body as Partial<Account>) };
      if (patch.handle !== undefined) {
        patch.handle = patch.handle.trim().replace(/^@/, "");
      }
      Object.assign(account, patch, { updated_at: LATER });
      return json(200, account);
    }
    return json(404, errorBody("not_found", "Not found."));
  }
}

const VIDEO_FORMATS: MediaFormat[] = ["mp4", "mov", "webm"];

function formatFromName(name: string): MediaFormat | null {
  const extension = name.split(".").pop()?.toLowerCase() ?? "";
  const formats: Record<string, MediaFormat> = {
    jpg: "jpeg",
    jpeg: "jpeg",
    png: "png",
    webp: "webp",
    mp4: "mp4",
    mov: "mov",
    webm: "webm",
  };
  return formats[extension] ?? null;
}

export function duplicateError(field: string, message: string) {
  return errorBody("duplicate", message, [{ field, message }]);
}
