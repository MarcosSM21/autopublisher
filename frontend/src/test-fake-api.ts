// In-memory stand-in for the backend API used by UI tests (see contracts/api.md).
import { vi } from "vitest";
import type {
  Account,
  Content,
  ImportItemResult,
  MediaFormat,
  Project,
  Publication,
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

/** What the fake backend stores; effective metadata is computed on read. */
type PublicationRecord = Pick<
  Publication,
  | "id"
  | "project_id"
  | "content_id"
  | "account_id"
  | "status"
  | "scheduled_at"
  | "title_override"
  | "description_override"
  | "hashtags_override"
  | "created_at"
  | "updated_at"
>;

const PLATFORM_NAMES: Record<string, string> = {
  youtube: "YouTube",
  instagram: "Instagram",
  tiktok: "TikTok",
  x: "X",
  threads: "Threads",
  telegram: "Telegram",
};

function accountName(account: Account): string {
  return `${PLATFORM_NAMES[account.platform]} @${account.handle}`;
}

const TIMESTAMP = "2026-10-05T10:00:00Z";
const LATER = "2026-10-05T11:00:00Z";

export class FakeApi {
  projects: Project[] = [];
  accounts: Account[] = [];
  contents: Content[] = [];
  publications: PublicationRecord[] = [];
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

  addPublication(
    values: Partial<PublicationRecord> &
      Pick<PublicationRecord, "content_id" | "account_id">,
  ): Publication {
    const content = this.contents.find((c) => c.id === values.content_id)!;
    const record: PublicationRecord = {
      id: this.nextId++,
      project_id: content.project_id,
      status: values.scheduled_at ? "scheduled" : "unscheduled",
      scheduled_at: null,
      title_override: null,
      description_override: null,
      hashtags_override: null,
      created_at: TIMESTAMP,
      updated_at: TIMESTAMP,
      ...values,
    };
    this.publications.push(record);
    return this.publicationView(record);
  }

  /** Builds the API representation, like publication_to_read in the backend. */
  publicationView(record: PublicationRecord): Publication {
    const content = this.contents.find((c) => c.id === record.content_id)!;
    const account = this.accounts.find((a) => a.id === record.account_id)!;
    const project = this.projects.find((p) => p.id === record.project_id)!;
    return {
      ...record,
      title: record.title_override ?? content.title,
      description: record.description_override ?? content.description,
      hashtags: record.hashtags_override ?? content.hashtags,
      content: {
        id: content.id,
        title: content.title,
        original_filename: content.original_filename,
        media_type: content.media_type,
        file_url: content.file_url,
        file_available: content.file_available,
      },
      account: {
        id: account.id,
        platform: account.platform,
        handle: account.handle,
        display_name: account.display_name,
        is_active: account.is_active,
      },
      project_active: project.is_active,
    };
  }

  /** Simplified preparation rules: see contracts/api.md. */
  private preparationError(
    content: Content,
    accounts: Account[],
  ): Response | null {
    const project = this.projects.find((p) => p.id === content.project_id)!;
    if (!project.is_active) {
      return json(
        409,
        errorBody(
          "project_inactive",
          "Reactivate the project before scheduling publications.",
        ),
      );
    }
    if (!content.file_available) {
      return json(
        409,
        errorBody(
          "media_unavailable",
          "The media file of this content is not available.",
        ),
      );
    }
    const inactive = accounts.filter((account) => !account.is_active);
    if (inactive.length > 0) {
      return json(
        409,
        errorBody(
          "account_inactive",
          "Reactivate the account before scheduling publications.",
          inactive.map((account) => ({
            field: "account_ids",
            message: `${accountName(account)} is inactive.`,
          })),
        ),
      );
    }
    return null;
  }

  private activeFor(
    contentId: number,
    accountId: number,
    excludeId?: number,
  ): PublicationRecord | undefined {
    return this.publications.find(
      (p) =>
        p.content_id === contentId &&
        p.account_id === accountId &&
        p.status !== "cancelled" &&
        p.id !== excludeId,
    );
  }

  private sortedPublications(projectId: number): Publication[] {
    const rank = { scheduled: 0, unscheduled: 1, cancelled: 2 };
    return this.publications
      .filter((p) => p.project_id === projectId)
      .sort((a, b) => {
        if (a.status !== b.status) {
          return rank[a.status] - rank[b.status];
        }
        if (a.status === "scheduled" && a.scheduled_at !== b.scheduled_at) {
          return a.scheduled_at! < b.scheduled_at! ? -1 : 1;
        }
        if (a.status === "cancelled" && a.updated_at !== b.updated_at) {
          return a.updated_at < b.updated_at ? 1 : -1;
        }
        return a.id - b.id;
      })
      .map((p) => this.publicationView(p));
  }

  private handlePublications(
    path: string,
    method: string,
    body: unknown,
  ): Response | null {
    let match: RegExpMatchArray | null;
    if ((match = path.match(/^\/projects\/(\d+)\/publications$/))) {
      const projectId = Number(match[1]);
      if (!this.projects.some((p) => p.id === projectId)) {
        return json(404, errorBody("not_found", "Project not found."));
      }
      return json(200, this.sortedPublications(projectId));
    }
    if (
      (match = path.match(/^\/contents\/(\d+)\/publications$/)) &&
      method === "POST"
    ) {
      const content = this.contents.find((c) => c.id === Number(match![1]));
      if (!content) {
        return json(404, errorBody("not_found", "Content not found."));
      }
      const values = body as { account_ids: number[]; scheduled_at?: string };
      const ids = [...new Set(values.account_ids)];
      const accounts = ids.map((id) => this.accounts.find((a) => a.id === id)!);
      const error = this.preparationError(content, accounts);
      if (error) {
        return error;
      }
      const conflicts = accounts.filter((account) =>
        this.activeFor(content.id, account.id),
      );
      if (conflicts.length > 0) {
        return json(
          409,
          errorBody(
            "duplicate",
            "Some accounts already have an active publication of this content.",
            conflicts.map((account) => ({
              field: "account_ids",
              message: `${accountName(account)} already has an active publication of this content.`,
            })),
          ),
        );
      }
      const created = accounts.map((account) =>
        this.addPublication({
          content_id: content.id,
          account_id: account.id,
          scheduled_at: values.scheduled_at ?? null,
          created_at: LATER,
          updated_at: LATER,
        }),
      );
      return json(201, created);
    }
    if ((match = path.match(/^\/publications\/(\d+)(\/\w+)?$/))) {
      const record = this.publications.find((p) => p.id === Number(match![1]));
      if (!record) {
        return json(404, errorBody("not_found", "Publication not found."));
      }
      const action = match[2];
      const content = this.contents.find((c) => c.id === record.content_id)!;
      const account = this.accounts.find((a) => a.id === record.account_id)!;
      if (action === "/cancel" && method === "POST") {
        if (record.status !== "cancelled") {
          Object.assign(record, { status: "cancelled", updated_at: LATER });
        }
      } else if (action === "/reactivate" && method === "POST") {
        if (record.status !== "cancelled") {
          return json(
            409,
            errorBody(
              "publication_not_cancelled",
              "This publication is not cancelled.",
            ),
          );
        }
        const error = this.preparationError(content, [account]);
        if (error) {
          return error;
        }
        if (this.activeFor(record.content_id, record.account_id, record.id)) {
          return json(
            409,
            errorBody(
              "duplicate",
              `${accountName(account)} already has an active publication of this content.`,
            ),
          );
        }
        const future =
          record.scheduled_at !== null &&
          new Date(record.scheduled_at).getTime() > Date.now();
        Object.assign(record, {
          status: future ? "scheduled" : "unscheduled",
          scheduled_at: future ? record.scheduled_at : null,
          updated_at: LATER,
        });
      } else if (action === undefined && method === "PATCH") {
        if (record.status === "cancelled") {
          return json(
            409,
            errorBody(
              "publication_cancelled",
              "Reactivate the publication before editing it.",
            ),
          );
        }
        const patch = body as Partial<PublicationRecord>;
        if (
          patch.scheduled_at !== undefined &&
          patch.scheduled_at !== null &&
          patch.scheduled_at !== record.scheduled_at
        ) {
          const error = this.preparationError(content, [account]);
          if (error) {
            return error;
          }
        }
        if (patch.hashtags_override) {
          patch.hashtags_override = patch.hashtags_override.map((tag) =>
            tag.replace(/^#/, ""),
          );
        }
        Object.assign(record, patch, { updated_at: LATER });
        if (patch.scheduled_at !== undefined) {
          record.status = patch.scheduled_at ? "scheduled" : "unscheduled";
        }
      } else if (action !== undefined || method !== "GET") {
        return null;
      }
      return json(200, this.publicationView(record));
    }
    return null;
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

    const publicationResponse = this.handlePublications(path, method, body);
    if (publicationResponse) {
      return publicationResponse;
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
