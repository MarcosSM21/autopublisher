// In-memory stand-in for the backend API used by UI tests (see contracts/api.md).
import { vi } from "vitest";
import type { Account, Project } from "./types.ts";

interface FailureResponse {
  status: number;
  body: unknown;
}

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
  requests: { method: string; path: string; body: unknown }[] = [];
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

  failNext(status: number, body: unknown): void {
    this.failures.push({ status, body });
  }

  install(): void {
    vi.stubGlobal(
      "fetch",
      vi.fn((input: string, init?: RequestInit) =>
        Promise.resolve(this.handle(input, init)),
      ),
    );
  }

  private handle(url: string, init?: RequestInit): Response {
    const method = init?.method ?? "GET";
    const path = url.replace(/^\/api/, "");
    const body: unknown = init?.body ? JSON.parse(String(init.body)) : null;
    this.requests.push({ method, path, body });

    const failure = method === "GET" ? undefined : this.failures.shift();
    if (failure) {
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

export function duplicateError(field: string, message: string) {
  return errorBody("duplicate", message, [{ field, message }]);
}
