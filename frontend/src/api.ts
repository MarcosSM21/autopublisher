import type {
  Account,
  AuthorizeResult,
  Content,
  FieldError,
  ImportResult,
  Platform,
  OAuthAttempt,
  Project,
  Publication,
  PublicationAttempt,
  PublishCheck,
  YouTubeConnection,
  YouTubePrivacy,
  YouTubePublicationOptions,
} from "./types.ts";

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
    // FormData bodies need the browser to set the multipart boundary itself.
    const headers =
      typeof init?.body === "string"
        ? { "Content-Type": "application/json", ...init.headers }
        : init?.headers;
    response = await fetch(`/api${path}`, { ...init, headers });
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

export function importFile(
  projectId: number,
  file: File,
): Promise<ImportResult> {
  const body = new FormData();
  body.append("files", file);
  return request<ImportResult>(`/projects/${projectId}/contents`, {
    method: "POST",
    body,
  });
}

export function getContent(id: number): Promise<Content> {
  return request<Content>(`/contents/${id}`);
}

export function listContents(projectId: number): Promise<Content[]> {
  return request<Content[]>(`/projects/${projectId}/contents`);
}

export type ContentUpdate = Partial<{
  title: string | null;
  description: string | null;
  hashtags: string[];
}>;

export function updateContent(
  id: number,
  changes: ContentUpdate,
): Promise<Content> {
  return request<Content>(`/contents/${id}`, {
    method: "PATCH",
    body: JSON.stringify(changes),
  });
}

export function listPublications(projectId: number): Promise<Publication[]> {
  return request<Publication[]>(`/projects/${projectId}/publications`);
}

export interface PublicationCreate {
  account_ids: number[];
  scheduled_at?: string;
}

export function createPublications(
  contentId: number,
  values: PublicationCreate,
): Promise<Publication[]> {
  return request<Publication[]>(`/contents/${contentId}/publications`, {
    method: "POST",
    body: JSON.stringify(values),
  });
}

export function getPublication(id: number): Promise<Publication> {
  return request<Publication>(`/publications/${id}`);
}

/** null removes the date or an override (the content's value is used again). */
export type PublicationUpdate = Partial<{
  scheduled_at: string | null;
  title_override: string | null;
  description_override: string | null;
  hashtags_override: string[] | null;
}>;

export function updatePublication(
  id: number,
  changes: PublicationUpdate,
): Promise<Publication> {
  return request<Publication>(`/publications/${id}`, {
    method: "PATCH",
    body: JSON.stringify(changes),
  });
}

export function cancelPublication(id: number): Promise<Publication> {
  return request<Publication>(`/publications/${id}/cancel`, { method: "POST" });
}

export function reactivatePublication(id: number): Promise<Publication> {
  return request<Publication>(`/publications/${id}/reactivate`, {
    method: "POST",
  });
}

export interface YouTubeOptionsInput {
  privacy_status: YouTubePrivacy;
  made_for_kids: boolean | null;
  contains_synthetic_media: boolean | null;
  notify_subscribers: boolean;
}

export function getYouTubeOptions(
  publicationId: number,
): Promise<YouTubePublicationOptions> {
  return request<YouTubePublicationOptions>(
    `/publications/${publicationId}/youtube-options`,
  );
}

export function saveYouTubeOptions(
  publicationId: number,
  values: YouTubeOptionsInput,
): Promise<YouTubePublicationOptions> {
  return request<YouTubePublicationOptions>(
    `/publications/${publicationId}/youtube-options`,
    { method: "PUT", body: JSON.stringify(values) },
  );
}

export function getPublishCheck(publicationId: number): Promise<PublishCheck> {
  return request<PublishCheck>(`/publications/${publicationId}/publish-check`);
}

/** Starts the upload and returns at once; poll getPublication for progress. */
export function publishNow(
  publicationId: number,
  confirmRemoteChecked = false,
): Promise<Publication> {
  return request<Publication>(`/publications/${publicationId}/publish`, {
    method: "POST",
    body: JSON.stringify({ confirm_remote_checked: confirmRemoteChecked }),
  });
}

export function listAttempts(
  publicationId: number,
): Promise<PublicationAttempt[]> {
  return request<PublicationAttempt[]>(
    `/publications/${publicationId}/attempts`,
  );
}

export function getYouTubeConnection(
  accountId: number,
): Promise<YouTubeConnection> {
  return request<YouTubeConnection>(
    `/accounts/${accountId}/youtube-connection`,
  );
}

export function authorizeYouTube(accountId: number): Promise<AuthorizeResult> {
  return request<AuthorizeResult>(
    `/accounts/${accountId}/youtube-connection/authorize`,
    { method: "POST" },
  );
}

export function getOAuthAttempt(attemptId: string): Promise<OAuthAttempt> {
  return request<OAuthAttempt>(
    `/youtube/oauth/attempts/${encodeURIComponent(attemptId)}`,
  );
}

export function confirmOAuthAttempt(attemptId: string): Promise<OAuthAttempt> {
  return request<OAuthAttempt>(
    `/youtube/oauth/attempts/${encodeURIComponent(attemptId)}/confirm`,
    { method: "POST" },
  );
}

export function cancelOAuthAttempt(attemptId: string): Promise<OAuthAttempt> {
  return request<OAuthAttempt>(
    `/youtube/oauth/attempts/${encodeURIComponent(attemptId)}/cancel`,
    { method: "POST" },
  );
}

export function verifyYouTubeConnection(
  accountId: number,
): Promise<YouTubeConnection> {
  return request<YouTubeConnection>(
    `/accounts/${accountId}/youtube-connection/verify`,
    { method: "POST" },
  );
}

export function disconnectYouTube(
  accountId: number,
): Promise<YouTubeConnection> {
  return request<YouTubeConnection>(
    `/accounts/${accountId}/youtube-connection/disconnect`,
    { method: "POST" },
  );
}
