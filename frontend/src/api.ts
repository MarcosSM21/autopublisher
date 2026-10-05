import type { Account, FieldError, Platform, Project } from "./types.ts";

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly fields: FieldError[];

  constructor(
    status: number,
    code: string,
    message: string,
    fields: FieldError[] = [],
  ) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.fields = fields;
  }

  fieldMessage(field: string): string | undefined {
    return this.fields.find((error) => error.field === field)?.message;
  }
}

interface ErrorBody {
  error: { code: string; message: string; fields?: FieldError[] };
}

function isErrorBody(body: unknown): body is ErrorBody {
  if (typeof body !== "object" || body === null || !("error" in body)) {
    return false;
  }
  const error = (body as { error: unknown }).error;
  return (
    typeof error === "object" &&
    error !== null &&
    typeof (error as { code?: unknown }).code === "string" &&
    typeof (error as { message?: unknown }).message === "string"
  );
}

export async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`/api${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...init?.headers },
    });
  } catch {
    throw new ApiError(0, "network_error", "Could not reach the server.");
  }

  let body: unknown = null;
  try {
    body = await response.json();
  } catch {
    body = null;
  }

  if (response.ok) {
    return body as T;
  }
  if (isErrorBody(body)) {
    throw new ApiError(
      response.status,
      body.error.code,
      body.error.message,
      body.error.fields ?? [],
    );
  }
  throw new ApiError(
    response.status,
    "unexpected_error",
    "The server returned an unexpected response.",
  );
}

export interface ProjectInput {
  name: string;
  description: string | null;
}

export function listProjects(): Promise<Project[]> {
  return request<Project[]>("/projects");
}

export function createProject(values: ProjectInput): Promise<Project> {
  return request<Project>("/projects", {
    method: "POST",
    body: JSON.stringify(values),
  });
}

export interface AccountInput {
  platform: Platform;
  handle: string;
  display_name: string | null;
}

export function listAccounts(projectId: number): Promise<Account[]> {
  return request<Account[]>(`/projects/${projectId}/accounts`);
}

export function createAccount(
  projectId: number,
  values: AccountInput,
): Promise<Account> {
  return request<Account>(`/projects/${projectId}/accounts`, {
    method: "POST",
    body: JSON.stringify(values),
  });
}

export type ProjectUpdate = Partial<ProjectInput & { is_active: boolean }>;

export function updateProject(
  id: number,
  changes: ProjectUpdate,
): Promise<Project> {
  return request<Project>(`/projects/${id}`, {
    method: "PATCH",
    body: JSON.stringify(changes),
  });
}

export type AccountUpdate = Partial<{
  handle: string;
  display_name: string | null;
  is_active: boolean;
}>;

export function updateAccount(
  id: number,
  changes: AccountUpdate,
): Promise<Account> {
  return request<Account>(`/accounts/${id}`, {
    method: "PATCH",
    body: JSON.stringify(changes),
  });
}
