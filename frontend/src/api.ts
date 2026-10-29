import type {
  AccountCapability,
  AnalyticsCatalog,
  AnalyticsPostsQuery,
  CheckStatusResult,
  Account,
  AccountHealth,
  AssetUsage,
  AuthSession,
  AuthorizeResult,
  AutomationStatus,
  Content,
  ContentSideBySide,
  ContentTypeSummary,
  DeletionPreview,
  DistributionPreset,
  FieldError,
  ImportResult,
  InstagramPublicationOptions,
  LibraryFolderRead,
  LibraryFolders,
  MetadataReport,
  SystemStatus,
  ThreadsPublicationOptions,
  TikTokCreatorInfo,
  TikTokDelivery,
  TikTokPublicationOptions,
  TikTokPublicationOptionsWrite,
  InstagramAuthorizeResult,
  InstagramConnection,
  InstagramOAuthAttempt,
  ThreadsAuthorizeResult,
  ThreadsConnection,
  ThreadsOAuthAttempt,
  TikTokAuthorizeResult,
  TikTokConnection,
  TikTokDisconnectResult,
  TikTokOAuthAttempt,
  Platform,
  OAuthAttempt,
  Overview,
  PlatformAvailability,
  PostAnalyticsRow,
  Project,
  ProjectRefreshResult,
  Publication,
  PublicationAttempt,
  PublishCheck,
  SingleDeletionKind,
  TelegramChannel,
  TelegramConnection,
  YouTubeConnection,
  YouTubePrivacy,
  YouTubePublicationOptions,
} from "./types.ts";

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly fields: FieldError[];
  /** Extra, safe members of the error object (e.g. `available_at`, `reason`). */
  readonly details: Record<string, unknown>;

  constructor(
    status: number,
    code: string,
    message: string,
    fields: FieldError[] = [],
    details: Record<string, unknown> = {},
  ) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.fields = fields;
    this.details = details;
  }

  fieldMessage(field: string): string | undefined {
    return this.fields.find((error) => error.field === field)?.message;
  }
}

interface ErrorBody {
  error: {
    code: string;
    message: string;
    fields?: FieldError[];
    [detail: string]: unknown;
  };
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

/**
 * Called when a request comes back `401 auth_required`: the session ended. Only
 * the session guard answers that code, so 403 (Host/Origin), 409 or a wrong
 * password never sign anyone out. The auth bootstrap registers the handler.
 */
let authRequiredHandler: (() => void) | null = null;

export function onAuthRequired(handler: (() => void) | null): void {
  authRequiredHandler = handler;
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
    if (response.status === 401 && body.error.code === "auth_required") {
      authRequiredHandler?.();
    }
    const { code, message, fields, ...details } = body.error;
    throw new ApiError(response.status, code, message, fields ?? [], details);
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

export function getProject(id: number): Promise<Project> {
  return request<Project>(`/projects/${id}`);
}

export function createProject(values: ProjectInput): Promise<Project> {
  return request<Project>("/projects", {
    method: "POST",
    body: JSON.stringify(values),
  });
}

/** Without a handle the account is provisional: its identity comes on connect. */
export interface AccountInput {
  platform: Platform;
  handle?: string;
  display_name?: string | null;
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

// --- Read-models (Feature 018): derived by the backend, shown as they come. ---

/** Global overview, or restricted to one project (404 if it does not exist). */
export function getOverview(projectId?: number): Promise<Overview> {
  return request<Overview>(
    projectId === undefined ? "/overview" : `/overview?project_id=${projectId}`,
  );
}

export function getAccountHealth(projectId: number): Promise<AccountHealth[]> {
  return request<AccountHealth[]>(`/projects/${projectId}/account-health`);
}

export function listPlatforms(): Promise<PlatformAvailability[]> {
  return request<PlatformAvailability[]>("/platforms");
}

/** The REST collection of each deletable kind (contracts/api.md §1). */
const DELETION_PATHS: Record<SingleDeletionKind, string> = {
  post: "/publications",
  media: "/contents",
  account: "/accounts",
  project: "/projects",
  folder: "/library-folders",
};

/** What deleting the object would remove, with the token that confirms it. */
export function getDeletionPreview(
  kind: SingleDeletionKind,
  id: number,
): Promise<DeletionPreview> {
  return request<DeletionPreview>(
    `${DELETION_PATHS[kind]}/${id}/deletion-preview`,
  );
}

/**
 * Deletes exactly the scope the preview described: `confirmation` is its token,
 * never built here. A changed scope answers `409 deletion_changed`.
 */
export async function deleteObject(
  kind: SingleDeletionKind,
  id: number,
  confirmation: string,
): Promise<void> {
  await request<null>(
    `${DELETION_PATHS[kind]}/${id}?confirmation=${encodeURIComponent(confirmation)}`,
    { method: "DELETE" },
  );
}

export function updateAccount(
  id: number,
  changes: AccountUpdate,
): Promise<Account> {
  return request<Account>(`/accounts/${id}`, {
    method: "PATCH",
    body: JSON.stringify(changes),
  });
}

/** Imports into a folder, or into Unsorted when `folderId` is null. */
export function importFile(
  projectId: number,
  file: File,
  folderId: number | null = null,
): Promise<ImportResult> {
  const body = new FormData();
  body.append("files", file);
  // The import's destination is `folder_id`; `folder` only filters a listing.
  const query = folderId === null ? "" : `?folder_id=${folderId}`;
  return request<ImportResult>(`/projects/${projectId}/contents${query}`, {
    method: "POST",
    body,
  });
}

export function getContent(id: number): Promise<Content> {
  return request<Content>(`/contents/${id}`);
}

export function getContentUsage(contentId: number): Promise<AssetUsage> {
  return request<AssetUsage>(`/contents/${contentId}/usage`);
}

export function inspectContentMetadata(
  contentId: number,
): Promise<MetadataReport> {
  return request<MetadataReport>(`/contents/${contentId}/metadata`);
}

/** Creates the clean copy publications send (or marks the content clean). */
export function removeMetadata(contentId: number): Promise<Content> {
  return request<Content>(`/contents/${contentId}/remove-metadata`, {
    method: "POST",
  });
}

/** A Library view: every Media, those without a folder, or one folder's own. */
export type LibraryScope =
  { kind: "all" } | { kind: "unsorted" } | { kind: "folder"; folderId: number };

const ALL_MEDIA: LibraryScope = { kind: "all" };

export function listContents(
  projectId: number,
  scope: LibraryScope = ALL_MEDIA,
): Promise<Content[]> {
  const query =
    scope.kind === "all"
      ? ""
      : `?folder=${scope.kind === "unsorted" ? "unsorted" : scope.folderId}`;
  return request<Content[]>(`/projects/${projectId}/contents${query}`);
}

/** Moves every Media or none; `folderId` null moves them to Unsorted. */
export function moveContents(
  projectId: number,
  contentIds: number[],
  folderId: number | null,
): Promise<{ moved: number }> {
  return request<{ moved: number }>(`/projects/${projectId}/contents/move`, {
    method: "POST",
    body: JSON.stringify({ content_ids: contentIds, folder_id: folderId }),
  });
}

/** What deleting the selected Media would remove: one aggregate, read-only. */
export function getMediaSelectionDeletionPreview(
  projectId: number,
  contentIds: number[],
): Promise<DeletionPreview> {
  return request<DeletionPreview>(
    `/projects/${projectId}/contents/deletion-preview`,
    { method: "POST", body: JSON.stringify({ content_ids: contentIds }) },
  );
}

/** Deletes every selected Media and their posts, or none of them. */
export async function deleteMediaSelection(
  projectId: number,
  contentIds: number[],
  confirmation: string,
): Promise<void> {
  await request<null>(`/projects/${projectId}/contents/delete`, {
    method: "POST",
    body: JSON.stringify({ content_ids: contentIds, confirmation }),
  });
}

export function listLibraryFolders(projectId: number): Promise<LibraryFolders> {
  return request<LibraryFolders>(`/projects/${projectId}/library-folders`);
}

/** `parentId` null creates a top-level folder. */
export function createLibraryFolder(
  projectId: number,
  name: string,
  parentId: number | null,
): Promise<LibraryFolderRead> {
  return request<LibraryFolderRead>(`/projects/${projectId}/library-folders`, {
    method: "POST",
    body: JSON.stringify({ name, parent_id: parentId }),
  });
}

export function renameLibraryFolder(
  folderId: number,
  name: string,
): Promise<LibraryFolderRead> {
  return request<LibraryFolderRead>(`/library-folders/${folderId}`, {
    method: "PATCH",
    body: JSON.stringify({ name }),
  });
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

/** Omitted or null: no override at this level; "" or []: explicit empty override. */
export interface PublicationOverrides {
  title_override?: string | null;
  description_override?: string | null;
  hashtags_override?: string[] | null;
}

export interface PublicationCreate extends PublicationOverrides {
  account_ids: number[];
  scheduled_at?: string;
  /** Requires scheduled_at; publishes automatically when the time comes. */
  auto_publish_enabled?: boolean;
  /** Per destination (key = account id): overrides the common values. */
  targets?: Record<number, PublicationOverrides>;
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

export function listDistributionPresets(
  projectId: number,
): Promise<DistributionPreset[]> {
  return request<DistributionPreset[]>(
    `/projects/${projectId}/distribution-presets`,
  );
}

export interface DistributionPresetInput {
  name: string;
  account_ids: number[];
}

export function createDistributionPreset(
  projectId: number,
  values: DistributionPresetInput,
): Promise<DistributionPreset> {
  return request<DistributionPreset>(
    `/projects/${projectId}/distribution-presets`,
    { method: "POST", body: JSON.stringify(values) },
  );
}

/** `account_ids` replaces the whole set of destinations. */
export function updateDistributionPreset(
  id: number,
  changes: Partial<DistributionPresetInput>,
): Promise<DistributionPreset> {
  return request<DistributionPreset>(`/distribution-presets/${id}`, {
    method: "PATCH",
    body: JSON.stringify(changes),
  });
}

export function deleteDistributionPreset(id: number): Promise<void> {
  return request<void>(`/distribution-presets/${id}`, { method: "DELETE" });
}

export interface TextPublicationCreate {
  account_ids: number[];
  /** The text of the post (stored as the description override). */
  description: string | null;
  hashtags: string[];
  scheduled_at?: string;
  /** Requires scheduled_at; publishes automatically when the time comes. */
  auto_publish_enabled?: boolean;
}

/** Publications without content, one per account (text posts). */
export function createTextPublications(
  projectId: number,
  values: TextPublicationCreate,
): Promise<Publication[]> {
  return request<Publication[]>(`/projects/${projectId}/text-publications`, {
    method: "POST",
    body: JSON.stringify(values),
  });
}

export function getPublication(id: number): Promise<Publication> {
  return request<Publication>(`/publications/${id}`);
}

/**
 * null removes the date or an override (the content's value is used again). For
 * a failed post, sending `scheduled_at` (even null) reschedules it or moves it
 * back to drafts; it fails with `check_result_first` while the result of its
 * last attempt is uncertain.
 */
export type PublicationUpdate = Partial<{
  scheduled_at: string | null;
  /** Changing scheduled_at without this field leaves the publication disarmed. */
  auto_publish_enabled: boolean;
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

export interface InstagramOptionsInput {
  is_ai_generated: boolean | null;
  /** Reels only. */
  share_to_feed?: boolean;
  /** Images only. */
  alt_text?: string | null;
}

export function getInstagramOptions(
  publicationId: number,
): Promise<InstagramPublicationOptions> {
  return request<InstagramPublicationOptions>(
    `/publications/${publicationId}/instagram-options`,
  );
}

export function saveInstagramOptions(
  publicationId: number,
  values: InstagramOptionsInput,
): Promise<InstagramPublicationOptions> {
  return request<InstagramPublicationOptions>(
    `/publications/${publicationId}/instagram-options`,
    { method: "PUT", body: JSON.stringify(values) },
  );
}

export interface ThreadsOptionsInput {
  /** Images and videos only; null or empty removes it. */
  alt_text: string | null;
}

export function getThreadsOptions(
  publicationId: number,
): Promise<ThreadsPublicationOptions> {
  return request<ThreadsPublicationOptions>(
    `/publications/${publicationId}/threads-options`,
  );
}

export function saveThreadsOptions(
  publicationId: number,
  values: ThreadsOptionsInput,
): Promise<ThreadsPublicationOptions> {
  return request<ThreadsPublicationOptions>(
    `/publications/${publicationId}/threads-options`,
    { method: "PUT", body: JSON.stringify(values) },
  );
}

export function getTikTokOptions(
  publicationId: number,
): Promise<TikTokPublicationOptions> {
  return request<TikTokPublicationOptions>(
    `/publications/${publicationId}/tiktok-options`,
  );
}

export function saveTikTokOptions(
  publicationId: number,
  values: TikTokPublicationOptionsWrite,
): Promise<TikTokPublicationOptions> {
  return request<TikTokPublicationOptions>(
    `/publications/${publicationId}/tiktok-options`,
    { method: "PUT", body: JSON.stringify(values) },
  );
}

/** Upload to Inbox delivery state of a TikTok publication (no network). */
export function getTikTokDelivery(
  publicationId: number,
): Promise<TikTokDelivery> {
  return request<TikTokDelivery>(
    `/publications/${publicationId}/tiktok-delivery`,
  );
}

/** One read-only check of a publication awaiting user action. */
export function checkPublicationStatus(
  publicationId: number,
): Promise<CheckStatusResult> {
  return request<CheckStatusResult>(
    `/publications/${publicationId}/check-status`,
    { method: "POST" },
  );
}

/** A fresh Creator Info read from TikTok (never cached). */
export function getTikTokCreatorInfo(
  publicationId: number,
): Promise<TikTokCreatorInfo> {
  return request<TikTokCreatorInfo>(
    `/publications/${publicationId}/tiktok-creator-info`,
  );
}

/** Records the consent for exactly the fingerprint and declaration shown. */
export function confirmTikTokConsent(
  publicationId: number,
  fingerprint: string,
  declarationVersion: string,
): Promise<TikTokPublicationOptions> {
  return request<TikTokPublicationOptions>(
    `/publications/${publicationId}/tiktok-consent`,
    {
      method: "POST",
      body: JSON.stringify({
        fingerprint,
        declaration_version: declarationVersion,
      }),
    },
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

// --- Installation sign-in and diagnostics (Feature 020) ------------------------

export function getAuthSession(): Promise<AuthSession> {
  return request<AuthSession>("/auth/session");
}

export async function login(password: string): Promise<void> {
  await request<null>("/auth/login", {
    method: "POST",
    body: JSON.stringify({ password }),
  });
}

/** Idempotent: also succeeds when the session had already ended. */
export async function logout(): Promise<void> {
  await request<null>("/auth/logout", { method: "POST" });
}

/** Other devices are signed out; this browser receives a new session. */
export async function changePassword(
  currentPassword: string,
  newPassword: string,
): Promise<void> {
  await request<null>("/auth/password", {
    method: "POST",
    body: JSON.stringify({
      current_password: currentPassword,
      new_password: newPassword,
    }),
  });
}

export function getSystemStatus(): Promise<SystemStatus> {
  return request<SystemStatus>("/system/status");
}

export function getAutomation(): Promise<AutomationStatus> {
  return request<AutomationStatus>("/automation");
}

export function setAutomationPaused(
  paused: boolean,
): Promise<AutomationStatus> {
  return request<AutomationStatus>("/automation", {
    method: "PUT",
    body: JSON.stringify({ paused }),
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

export function getInstagramConnection(
  accountId: number,
): Promise<InstagramConnection> {
  return request<InstagramConnection>(
    `/accounts/${accountId}/instagram-connection`,
  );
}

export function authorizeInstagram(
  accountId: number,
): Promise<InstagramAuthorizeResult> {
  return request<InstagramAuthorizeResult>(
    `/accounts/${accountId}/instagram-connection/authorize`,
    { method: "POST" },
  );
}

/** The pasted redirect URL (with `code` and `state`) only travels in the body. */
export function completeInstagramAttempt(
  attemptId: string,
  redirectUrl: string,
): Promise<InstagramOAuthAttempt> {
  return request<InstagramOAuthAttempt>(
    `/instagram/oauth/attempts/${encodeURIComponent(attemptId)}/complete`,
    { method: "POST", body: JSON.stringify({ redirect_url: redirectUrl }) },
  );
}

export function confirmInstagramAttempt(
  attemptId: string,
): Promise<InstagramOAuthAttempt> {
  return request<InstagramOAuthAttempt>(
    `/instagram/oauth/attempts/${encodeURIComponent(attemptId)}/confirm`,
    { method: "POST" },
  );
}

export function cancelInstagramAttempt(
  attemptId: string,
): Promise<InstagramOAuthAttempt> {
  return request<InstagramOAuthAttempt>(
    `/instagram/oauth/attempts/${encodeURIComponent(attemptId)}/cancel`,
    { method: "POST" },
  );
}

export function verifyInstagramConnection(
  accountId: number,
): Promise<InstagramConnection> {
  return request<InstagramConnection>(
    `/accounts/${accountId}/instagram-connection/verify`,
    { method: "POST" },
  );
}

export function disconnectInstagram(
  accountId: number,
): Promise<InstagramConnection> {
  return request<InstagramConnection>(
    `/accounts/${accountId}/instagram-connection/disconnect`,
    { method: "POST" },
  );
}

export function getThreadsConnection(
  accountId: number,
): Promise<ThreadsConnection> {
  return request<ThreadsConnection>(
    `/accounts/${accountId}/threads-connection`,
  );
}

export function authorizeThreads(
  accountId: number,
): Promise<ThreadsAuthorizeResult> {
  return request<ThreadsAuthorizeResult>(
    `/accounts/${accountId}/threads-connection/authorize`,
    { method: "POST" },
  );
}

/** The pasted redirect URL (with `code` and `state`) only travels in the body. */
export function completeThreadsAttempt(
  attemptId: string,
  redirectUrl: string,
): Promise<ThreadsOAuthAttempt> {
  return request<ThreadsOAuthAttempt>(
    `/threads/oauth/attempts/${encodeURIComponent(attemptId)}/complete`,
    { method: "POST", body: JSON.stringify({ redirect_url: redirectUrl }) },
  );
}

export function confirmThreadsAttempt(
  attemptId: string,
): Promise<ThreadsOAuthAttempt> {
  return request<ThreadsOAuthAttempt>(
    `/threads/oauth/attempts/${encodeURIComponent(attemptId)}/confirm`,
    { method: "POST" },
  );
}

export function cancelThreadsAttempt(
  attemptId: string,
): Promise<ThreadsOAuthAttempt> {
  return request<ThreadsOAuthAttempt>(
    `/threads/oauth/attempts/${encodeURIComponent(attemptId)}/cancel`,
    { method: "POST" },
  );
}

export function verifyThreadsConnection(
  accountId: number,
): Promise<ThreadsConnection> {
  return request<ThreadsConnection>(
    `/accounts/${accountId}/threads-connection/verify`,
    { method: "POST" },
  );
}

export function disconnectThreads(
  accountId: number,
): Promise<ThreadsConnection> {
  return request<ThreadsConnection>(
    `/accounts/${accountId}/threads-connection/disconnect`,
    { method: "POST" },
  );
}

export function getTikTokConnection(
  accountId: number,
): Promise<TikTokConnection> {
  return request<TikTokConnection>(`/accounts/${accountId}/tiktok-connection`);
}

export function authorizeTikTok(
  accountId: number,
): Promise<TikTokAuthorizeResult> {
  return request<TikTokAuthorizeResult>(
    `/accounts/${accountId}/tiktok-connection/authorize`,
    { method: "POST" },
  );
}

export function getTikTokAttempt(
  attemptId: string,
): Promise<TikTokOAuthAttempt> {
  return request<TikTokOAuthAttempt>(
    `/tiktok/oauth/attempts/${encodeURIComponent(attemptId)}`,
  );
}

export function cancelTikTokAttempt(
  attemptId: string,
): Promise<TikTokOAuthAttempt> {
  return request<TikTokOAuthAttempt>(
    `/tiktok/oauth/attempts/${encodeURIComponent(attemptId)}/cancel`,
    { method: "POST" },
  );
}

export function confirmTikTokAttempt(
  attemptId: string,
): Promise<TikTokOAuthAttempt> {
  return request<TikTokOAuthAttempt>(
    `/tiktok/oauth/attempts/${encodeURIComponent(attemptId)}/confirm`,
    { method: "POST" },
  );
}

export function verifyTikTokConnection(
  accountId: number,
): Promise<TikTokConnection> {
  return request<TikTokConnection>(
    `/accounts/${accountId}/tiktok-connection/verify`,
    { method: "POST" },
  );
}

/** Revoke in TikTok, then remove the connection. */
export function disconnectTikTok(
  accountId: number,
): Promise<TikTokDisconnectResult> {
  return request<TikTokDisconnectResult>(
    `/accounts/${accountId}/tiktok-connection/disconnect`,
    { method: "POST" },
  );
}

/** Remove the connection without revoking it in TikTok (explicit user choice). */
export function removeTikTokLocally(
  accountId: number,
): Promise<TikTokDisconnectResult> {
  return request<TikTokDisconnectResult>(
    `/accounts/${accountId}/tiktok-connection/remove-local`,
    { method: "POST" },
  );
}

function telegramPath(accountId: number, action: string = ""): string {
  return `/accounts/${accountId}/telegram-connection${action}`;
}

export function getTelegramConnection(
  accountId: number,
): Promise<TelegramConnection> {
  return request<TelegramConnection>(telegramPath(accountId));
}

/** The phone, code and password only travel in the body and are never kept. */
export function startTelegramLogin(
  accountId: number,
  phone: string,
): Promise<TelegramConnection> {
  return request<TelegramConnection>(telegramPath(accountId, "/login/start"), {
    method: "POST",
    body: JSON.stringify({ phone }),
  });
}

export function submitTelegramCode(
  accountId: number,
  code: string,
): Promise<TelegramConnection> {
  return request<TelegramConnection>(telegramPath(accountId, "/login/code"), {
    method: "POST",
    body: JSON.stringify({ code }),
  });
}

export function submitTelegramPassword(
  accountId: number,
  password: string,
): Promise<TelegramConnection> {
  return request<TelegramConnection>(
    telegramPath(accountId, "/login/password"),
    { method: "POST", body: JSON.stringify({ password }) },
  );
}

export function cancelTelegramLogin(
  accountId: number,
): Promise<TelegramConnection> {
  return request<TelegramConnection>(telegramPath(accountId, "/login/cancel"), {
    method: "POST",
  });
}

export function verifyTelegramConnection(
  accountId: number,
): Promise<TelegramConnection> {
  return request<TelegramConnection>(telegramPath(accountId, "/verify"), {
    method: "POST",
  });
}

export function disconnectTelegram(
  accountId: number,
): Promise<TelegramConnection> {
  return request<TelegramConnection>(telegramPath(accountId, "/disconnect"), {
    method: "POST",
  });
}

export function listTelegramChannels(
  accountId: number,
): Promise<TelegramChannel[]> {
  return request<{ channels: TelegramChannel[] }>(
    telegramPath(accountId, "/channels"),
  ).then((body) => body.channels);
}

export function setTelegramChannel(
  accountId: number,
  channelId: string,
): Promise<TelegramConnection> {
  return request<TelegramConnection>(telegramPath(accountId, "/channel"), {
    method: "PUT",
    body: JSON.stringify({ channel_id: channelId }),
  });
}

// --- Analytics (Feature 027) -------------------------------------------------------

export function getAnalyticsCatalog(): Promise<AnalyticsCatalog> {
  return request<AnalyticsCatalog>("/analytics/catalog");
}

export function getAnalyticsAccounts(
  projectId: number,
): Promise<AccountCapability[]> {
  return request<AccountCapability[]>(
    `/projects/${projectId}/analytics/accounts`,
  );
}

function analyticsQuery(query: AnalyticsPostsQuery): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value !== undefined && value !== "") params.set(key, String(value));
  }
  const text = params.toString();
  return text ? `?${text}` : "";
}

export function getAnalyticsPosts(
  projectId: number,
  query: AnalyticsPostsQuery = {},
): Promise<PostAnalyticsRow[]> {
  return request<PostAnalyticsRow[]>(
    `/projects/${projectId}/analytics/posts${analyticsQuery(query)}`,
  );
}

/** Medians per content type of one platform (`platform` is required). */
export function getContentTypeSummary(
  projectId: number,
  query: Omit<AnalyticsPostsQuery, "sort" | "order"> & { platform: Platform },
): Promise<ContentTypeSummary[]> {
  return request<ContentTypeSummary[]>(
    `/projects/${projectId}/analytics/content-types${analyticsQuery(query)}`,
  );
}

/** One media's published posts side by side (contracts §Side by side). */
export function getContentAnalytics(
  contentId: number,
): Promise<ContentSideBySide> {
  return request<ContentSideBySide>(`/contents/${contentId}/analytics`);
}

export function getPublicationAnalytics(
  publicationId: number,
): Promise<PostAnalyticsRow> {
  return request<PostAnalyticsRow>(`/publications/${publicationId}/analytics`);
}

/** Only enqueues: `409 refresh_cooldown` carries `details.available_at`. */
export function refreshPublicationAnalytics(
  publicationId: number,
): Promise<{ queued: boolean }> {
  return request<{ queued: boolean }>(
    `/publications/${publicationId}/analytics/refresh`,
    { method: "POST" },
  );
}

export function refreshProjectAnalytics(
  projectId: number,
): Promise<ProjectRefreshResult> {
  return request<ProjectRefreshResult>(
    `/projects/${projectId}/analytics/refresh`,
    { method: "POST" },
  );
}
