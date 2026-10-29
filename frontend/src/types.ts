// Keep in sync with Platform in backend/app/models.py.
export type Platform =
  "youtube" | "instagram" | "tiktok" | "x" | "threads" | "telegram";

export const PLATFORMS: ReadonlyArray<{ value: Platform; label: string }> = [
  { value: "youtube", label: "YouTube" },
  { value: "instagram", label: "Instagram" },
  { value: "tiktok", label: "TikTok" },
  { value: "x", label: "X" },
  { value: "threads", label: "Threads" },
  { value: "telegram", label: "Telegram" },
];

export function platformLabel(value: Platform): string {
  return PLATFORMS.find((platform) => platform.value === value)?.label ?? value;
}

export interface Project {
  id: number;
  name: string;
  description: string | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface Account {
  id: number;
  project_id: number;
  platform: Platform;
  /** null while the account is provisional (identity not known yet). */
  handle: string | null;
  display_name: string | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

/** A named set of destinations of a project; it stores nothing else. */
export interface DistributionPreset {
  id: number;
  project_id: number;
  name: string;
  account_ids: number[];
  created_at: string;
  updated_at: string;
}

export interface FieldError {
  field: string;
  message: string;
  /** The account the error is about, when it concerns one destination. */
  account_id?: number;
}

// Keep in sync with MediaType and MediaFormat in backend/app/models.py.
export type MediaType = "image" | "video";
export type MediaFormat = "jpeg" | "png" | "webp" | "mp4" | "mov" | "webm";

export const MEDIA_TYPE_LABELS: Record<MediaType, string> = {
  image: "Image",
  video: "Video",
};

export type MetadataStatus = "unknown" | "clean" | "sanitized";

/** The file publications send: the original or its clean copy. */
export interface PublishFile {
  version: "original" | "clean_copy";
  available: boolean;
  checksum: string;
  size_bytes: number;
  sanitized_at: string | null;
}

/**
 * Derived from the content's publications (never stored). The Feature 019 counts
 * follow the visible state computed by the backend (post_display_state).
 */
export interface ContentUsage {
  used: boolean;
  publication_count: number;
  published_count: number;
  awaiting_count: number;
  scheduled_count: number;
  platforms: Platform[];
  last_published_at: string | null;
  draft_count: number;
  /** Failed, needs review, needs action and missed. */
  attention_count: number;
  /** Publishing, or scheduled (automatic, manual or paused). */
  upcoming_count: number;
  next_scheduled_at: string | null;
  /** "Not used yet" ⇔ publication_count === cancelled_count. */
  cancelled_count: number;
}

/** Per text field, whether the post follows the media's value (no override). */
export interface FieldInheritance {
  title: boolean;
  description: boolean;
  hashtags: boolean;
}

/** One publication of a content in its usage history. */
export interface AssetPublication {
  publication_id: number;
  platform: Platform;
  account_id: number;
  account_name: string;
  status: PublicationStatus;
  scheduled_at: string | null;
  published_at: string | null;
  created_at: string;
  updated_at: string;
  uncertain: boolean;
  external_url: string | null;
  /** What the user sees; computed only by the backend. */
  display_state: PostDisplayState;
  inherits: FieldInheritance;
  /** A TikTok Direct Post consent covers the caption (editing it makes it stale). */
  consent_covers_caption: boolean;
}

export interface AssetUsage {
  usage: ContentUsage;
  publications: AssetPublication[];
}

export interface MetadataFinding {
  category: string;
  label: string;
  keys: string[];
}

export interface FileMetadataReport {
  inspected: boolean;
  reason: string | null;
  findings: MetadataFinding[];
}

export interface MetadataReport {
  original: FileMetadataReport;
  publish_copy: FileMetadataReport | null;
}

export interface Content {
  id: number;
  project_id: number;
  media_type: MediaType;
  media_format: MediaFormat;
  original_filename: string;
  title: string | null;
  description: string | null;
  hashtags: string[];
  checksum: string;
  size_bytes: number;
  width: number | null;
  height: number | null;
  duration_seconds: number | null;
  file_url: string;
  file_available: boolean;
  created_at: string;
  updated_at: string;
  metadata_status: MetadataStatus;
  publish_file: PublishFile;
  usage: ContentUsage;
  /** The Library folder the Media is in; null = Unsorted. */
  folder_id: number | null;
}

/** One folder of a project's Library tree (contracts/api.md §2). */
export interface LibraryFolder {
  id: number;
  parent_id: number | null;
  name: string;
  /** 1 for a top-level folder, at most MAX_FOLDER_DEPTH. */
  depth: number;
  /** Media assigned directly to this folder (not to its subfolders). */
  media_count: number;
}

export interface LibraryFolderRead extends LibraryFolder {
  project_id: number;
  created_at: string;
  updated_at: string;
}

/** The whole tree, ordered by depth then name, and the two virtual entries. */
export interface LibraryFolders {
  folders: LibraryFolder[];
  unsorted_count: number;
  total_count: number;
}

/** What a delete removes (contracts/api.md §1); keep in sync with DeletionKind. */
export type DeletionKind =
  | "post"
  | "media"
  | "account"
  | "project"
  | "folder"
  /** Several Media of one project at once (Feature 022). */
  | "media_selection";

/** The kinds deleted one object at a time, by id. */
export type SingleDeletionKind = Exclude<DeletionKind, "media_selection">;

export interface DeletionCounts {
  unpublished_posts: number;
  /** Published and Awaiting user action. */
  remote_posts: number;
  needs_review_posts: number;
  accounts: number;
  posts: number;
  media: number;
  subfolders: number;
  media_to_unsorted: number;
}

export interface DeletionBlocker {
  code: "post_in_progress" | "metadata_removal_in_progress";
  message: string;
}

/**
 * The one confirmation of a delete: the backend's ready-to-show summary and the
 * opaque token of the scope it describes, sent back unchanged with the DELETE.
 */
export interface DeletionPreview {
  kind: DeletionKind;
  /** Null only for `media_selection`: a selection has no single id nor name. */
  id: number | null;
  name: string | null;
  counts: DeletionCounts;
  summary: string[];
  blocker: DeletionBlocker | null;
  confirmation: string;
}

// Keep in sync with MAX_FOLDER_DEPTH and FolderName in backend/app/schemas.py.
export const MAX_FOLDER_DEPTH = 5;
export const MAX_FOLDER_NAME_LENGTH = 100;

export type ImportStatus = "imported" | "duplicate" | "rejected";

export interface ImportItemResult {
  filename: string;
  status: ImportStatus;
  content: Content | null;
  existing_content: Content | null;
  error: { code: string; message: string } | null;
}

export interface ImportResult {
  results: ImportItemResult[];
  summary: { imported: number; duplicates: number; rejected: number };
}

// Keep in sync with MAX_FILES_PER_IMPORT in backend/app/config.py.
export const MAX_FILES_PER_IMPORT = 100;

export const ACCEPTED_FILE_TYPES =
  "image/jpeg,image/png,image/webp,video/mp4,video/quicktime,video/webm," +
  ".jpg,.jpeg,.png,.webp,.mp4,.mov,.webm";

// Keep in sync with PublicationStatus in backend/app/models.py.
export type PublicationStatus =
  | "unscheduled"
  | "scheduled"
  | "cancelled"
  | "publishing"
  | "published"
  | "failed"
  | "awaiting_user_action";

// Keep in sync with HISTORY_STATUSES in backend/app/publications.py.
/** Statuses that no longer block a new publication of the same content. */
export const HISTORY_STATUSES: readonly PublicationStatus[] = [
  "cancelled",
  "published",
];

// Keep in sync with AttemptStatus and AttemptStage in backend/app/models.py.
export type AttemptStatus = "running" | "succeeded" | "failed";
export type AttemptStage =
  | "preparing"
  | "uploading"
  | "processing"
  | "finalizing"
  | "final_chunk"
  | "done";
// Keep in sync with AttemptTrigger in backend/app/models.py.
export type AttemptTrigger = "manual" | "scheduled";

/**
 * Derived automation state of a scheduled publication; never a status. "overdue"
 * means an armed publication missed its automatic window and stays scheduled.
 * Keep in sync with AutoPublishState in backend/app/models.py (see automation.py).
 */
export type AutoPublishState =
  "disabled" | "waiting" | "due" | "paused" | "overdue";

// --- Product states and read-models (Feature 018) ---------------------------------
// Keep in sync with backend/app/schemas.py.

export type PostDisplayState =
  | "draft"
  | "scheduled_automatic"
  | "scheduled_manual"
  | "scheduled_paused"
  | "publishing"
  | "published"
  | "failed"
  | "needs_review"
  | "needs_action"
  | "missed"
  | "cancelled";

export type AccountHealthState =
  | "ready"
  | "reconnect_needed"
  | "setup_required"
  | "not_connected"
  | "inactive";

export type PlatformStatus =
  "configured" | "partial" | "not_configured" | "coming_soon";

export type Capability = "text" | "images" | "videos";

export interface ProjectRef {
  id: number;
  name: string;
}

export interface AccountRef {
  id: number;
  platform: Platform;
  label: string;
}

export interface AttentionTarget {
  type: "post" | "account" | "settings";
  project_id?: number | null;
  id?: number | null;
}

export type AttentionKind =
  | "manual_review"
  | "failed"
  | "missed"
  | "needs_action"
  | "reconnect"
  | "incomplete"
  | "expiring";

export interface AttentionItem {
  kind: AttentionKind;
  priority: number;
  project: ProjectRef;
  account: AccountRef;
  post: {
    id: number;
    display_state: PostDisplayState;
    scheduled_at: string | null;
    media_title: string | null;
    excerpt: string | null;
  } | null;
  title: string;
  detail: string | null;
  at: string | null;
  action: { label: string; target: AttentionTarget };
  affected_posts: number;
}

export interface UpcomingPost {
  post_id: number;
  project: ProjectRef;
  account: AccountRef;
  scheduled_at: string;
  display_state: PostDisplayState;
  media_title: string | null;
  excerpt: string | null;
}

export interface ProjectSummary {
  id: number;
  name: string;
  is_active: boolean;
  accounts_active: number;
  accounts_ready: number;
  attention_count: number;
  next_post: {
    post_id: number;
    scheduled_at: string;
    display_state: PostDisplayState;
  } | null;
  onboarding: {
    account_ready: boolean;
    media_imported: boolean;
    post_created: boolean;
    complete: boolean;
  };
}

export interface Overview {
  generated_at: string;
  automation: {
    paused: boolean;
    running: boolean;
    paused_automatic_posts: number;
  };
  attention: AttentionItem[];
  upcoming: UpcomingPost[];
  projects: ProjectSummary[];
}

export interface AccountHealth {
  account_id: number;
  platform: Platform;
  label: string;
  display_name: string | null;
  is_active: boolean;
  state: AccountHealthState;
  identity: {
    name: string;
    username: string | null;
    avatar_url: string | null;
  } | null;
  expires_at: string | null;
  expiring: boolean;
  capabilities: Capability[];
  issue: { code: string; message: string } | null;
  can_discard: boolean;
}

export interface PlatformAvailability {
  platform: Platform;
  label: string;
  integration_available: boolean;
  status: PlatformStatus;
  can_connect: boolean;
  missing: Array<"app_credentials" | "media_delivery">;
  message: string | null;
}

/** Why the last automatic start failed; safe code and message only. */
export interface AutoPublishError {
  code: string;
  message: string;
  failed_at: string;
}

/** Global automation status of the local scheduler. */
/** GET /api/auth/session (Feature 020, contracts/api.md §3). */
export interface AuthSession {
  mode: "development" | "installation";
  auth_required: boolean;
  authenticated: boolean;
}

/** Non-interactive probe result; `unknown` never means "working". */
export type CredentialStoreStatus =
  "available" | "locked" | "unavailable" | "unknown";

/** GET /api/system/status (signed in; contracts/api.md §4). */
export interface SystemStatus {
  mode: "development" | "installation";
  database: { status: "ok" | "error" };
  credential_store: { status: CredentialStoreStatus };
  deployment: {
    port: number;
    lan_enabled: boolean;
    addresses: string[];
    suggested_names: string[];
    allowed_hosts: string[];
  } | null;
}

export interface AutomationStatus {
  paused: boolean;
  /** Whether the scheduler of the running backend is alive. */
  running: boolean;
  last_check_at: string | null;
  check_interval_seconds: number;
  window_minutes: number;
}

export interface PublicationWarning {
  code: string;
  message: string;
}

/** One real execution of a publication; never contains tokens or session URLs. */
export interface PublicationAttempt {
  id: number;
  publication_id: number;
  platform: Platform;
  trigger: AttemptTrigger;
  status: AttemptStatus;
  stage: AttemptStage;
  started_at: string;
  finished_at: string | null;
  bytes_sent: number;
  total_bytes: number;
  /** 0–1. */
  progress: number;
  error: { code: string; message: string } | null;
  /** null while running; false when the remote outcome is uncertain. */
  outcome_determined: boolean | null;
  requires_manual_review: boolean;
  external_id: string | null;
  external_url: string | null;
  /**
   * Non-sensitive snapshot of what was sent (platform-specific keys). With a
   * file, `file_checksum` is the SHA-256 of the file prepared for this attempt
   * (absent in older attempts); never the Media's current checksum.
   */
  submitted: Record<string, unknown>;
  /** Non-sensitive result details, e.g. privacy_status, processing_status. */
  details: Record<string, unknown>;
  warnings: PublicationWarning[];
}

export interface PublishProblem {
  code: string;
  message: string;
  field: string | null;
}

/** What "Publish now" would do, computed by the backend without network calls. */
export interface PublishCheck {
  eligible: boolean;
  problems: PublishProblem[];
  requires_remote_check: boolean;
  summary: { label: string; value: string }[];
  scheduled_at: string | null;
}

// Keep in sync with YouTubePrivacy in backend/app/models.py.
export type YouTubePrivacy = "private" | "unlisted" | "public";

export const YOUTUBE_PRIVACY_LABELS: Record<YouTubePrivacy, string> = {
  private: "Private",
  unlisted: "Unlisted",
  public: "Public",
};

export interface YouTubePublicationOptions {
  privacy_status: YouTubePrivacy;
  /** null means "not declared yet". */
  made_for_kids: boolean | null;
  contains_synthetic_media: boolean | null;
  notify_subscribers: boolean;
  complete: boolean;
  editable: boolean;
}

/** Keep in sync with InstagramMediaKind in backend/app/models.py. */
export type InstagramMediaKind = "image" | "reel";

/**
 * Instagram options of a publication, the exact caption that will be sent and the
 * problems detectable without network. Never contains provider details or URLs.
 */
export interface InstagramPublicationOptions {
  media_kind: InstagramMediaKind | null;
  caption: string;
  caption_length: number;
  caption_hashtags: number;
  caption_mentions: number;
  /** null means "not declared yet". */
  is_ai_generated: boolean | null;
  /** Reels only (null for images). */
  share_to_feed: boolean | null;
  /** Images only (null for Reels). */
  alt_text: string | null;
  complete: boolean;
  editable: boolean;
  media_delivery_configured: boolean;
  problems: PublishProblem[];
  limits: {
    caption_characters: number;
    caption_hashtags: number;
    caption_mentions: number;
    alt_text_characters: number;
  };
}

/** Keep in sync with ThreadsMediaKind in backend/app/models.py. */
export type ThreadsMediaKind = "text" | "image" | "video";

/**
 * Threads options of a publication, the exact text that will be sent and the
 * problems detectable without network. Never contains provider details or URLs.
 */
export interface ThreadsPublicationOptions {
  /** null when the content cannot be published on Threads. */
  media_kind: ThreadsMediaKind | null;
  text: string;
  text_length: number;
  text_links: number;
  /** Images and videos only (null for text posts). */
  alt_text: string | null;
  editable: boolean;
  media_delivery_required: boolean;
  media_delivery_configured: boolean;
  problems: PublishProblem[];
  limits: {
    text_characters: number;
    text_links: number;
    alt_text_characters: number;
  };
}

// Keep in sync with TikTokPrivacyLevel in backend/app/schemas.py.
export type TikTokPrivacyLevel =
  | "PUBLIC_TO_EVERYONE"
  | "MUTUAL_FOLLOW_FRIENDS"
  | "FOLLOWER_OF_CREATOR"
  | "SELF_ONLY";

export const TIKTOK_PRIVACY_LABELS: Record<TikTokPrivacyLevel, string> = {
  PUBLIC_TO_EVERYONE: "Everyone",
  MUTUAL_FOLLOW_FRIENDS: "Friends",
  FOLLOWER_OF_CREATOR: "Followers",
  SELF_ONLY: "Only me",
};

/** `stale`: consented, then something material changed. */
export type TikTokConsentState = "missing" | "valid" | "stale";

export interface TikTokDeclaration {
  version: string;
  text: string;
  links: { label: string; url: string }[];
}

/** The options the user chooses; null privacy or AIGC means "not chosen yet". */
// Keep in sync with TikTokMode in backend/app/models.py.
export type TikTokMode = "DIRECT_POST" | "INBOX_UPLOAD";

export interface TikTokPublicationOptionsWrite {
  /** null means "not chosen yet": there is never a default mode. */
  mode: TikTokMode | null;
  privacy_level: TikTokPrivacyLevel | null;
  allow_comment: boolean;
  allow_duet: boolean;
  allow_stitch: boolean;
  commercial_disclosure_enabled: boolean;
  brand_organic_toggle: boolean;
  brand_content_toggle: boolean;
  is_aigc: boolean | null;
}

/**
 * TikTok options of a publication, the exact caption, the declaration and the
 * consent state. Never contains tokens, the upload URL nor the publish id.
 */
export interface TikTokPublicationOptions extends TikTokPublicationOptionsWrite {
  /** Whether each mode can be chosen now, with the reason when it cannot. */
  modes: Record<TikTokMode, { available: boolean; reason: string | null }>;
  client_audited: boolean;
  allowed_privacy_levels: TikTokPrivacyLevel[];
  caption: string;
  caption_length: number;
  caption_max_length: number;
  declaration: TikTokDeclaration;
  labels: string[];
  /** Fingerprint of the current options; null while they are incomplete. */
  fingerprint: string | null;
  consent: { state: TikTokConsentState; consented_at: string | null };
  integrity_warning: { code: string; message: string; at: string } | null;
  problems: PublishProblem[];
  video: {
    format: string;
    size_bytes: number;
    duration_seconds: number | null;
    width: number | null;
    height: number | null;
    frame_rate: number | null;
    delegated_checks: string[];
    chunk_count: number;
  } | null;
  editable: boolean;
}

// Keep in sync with TikTokDeliveryRead in backend/app/schemas.py.
export type TikTokDeliveryState =
  | "not_sent"
  | "scheduled"
  | "uploading"
  | "processing"
  | "ready"
  | "published"
  | "failed";

/** Derived Upload to Inbox delivery state (no network, never the publish id). */
export interface TikTokDelivery {
  mode: TikTokMode | null;
  /** null when the publication is not sent with Upload to Inbox. */
  state: TikTokDeliveryState | null;
  delivered_at: string | null;
  user_published_at: string | null;
  /** TikTok reported a failure after the video reached the inbox. */
  after_delivery_failure: { code: string; message: string } | null;
  instruction: string | null;
  can_check_status: boolean;
}

/** One check of a publication awaiting user action on the platform. */
export interface CheckStatusResult {
  result: "awaiting" | "published" | "failed";
  message: string;
  checked_at: string;
  publication: Publication;
}

/** What TikTok reports now about the destination account; never stored. */
export interface TikTokCreatorInfo {
  nickname: string | null;
  username: string | null;
  /** Display only: a signed URL that expires after two hours. */
  avatar_url: string | null;
  privacy_level_options: string[] | null;
  comment_disabled: boolean | null;
  duet_disabled: boolean | null;
  stitch_disabled: boolean | null;
  max_video_post_duration_sec: number | null;
  can_post: boolean;
  blocked: { code: string; message: string } | null;
  account_appears_public: boolean;
  video_within_max_duration: boolean | null;
}

export interface PublicationContentSummary {
  id: number;
  title: string | null;
  original_filename: string;
  media_type: MediaType;
  file_url: string;
  file_available: boolean;
}

export interface PublicationAccountSummary {
  id: number;
  platform: Platform;
  handle: string | null;
  display_name: string | null;
  is_active: boolean;
}

export interface Publication {
  id: number;
  project_id: number;
  /** null for publications without media (text posts). */
  content_id: number | null;
  account_id: number;
  status: PublicationStatus;
  scheduled_at: string | null;
  /** null means the publication uses the content's value. */
  title_override: string | null;
  description_override: string | null;
  hashtags_override: string[] | null;
  /** Effective metadata: the override when set, otherwise the content's value. */
  title: string | null;
  description: string | null;
  hashtags: string[];
  content: PublicationContentSummary | null;
  account: PublicationAccountSummary;
  project_active: boolean;
  published_at: string | null;
  latest_attempt: PublicationAttempt | null;
  attempt_count: number;
  /** Explicit consent: AutoPublisher starts it by itself when its time comes. */
  auto_publish_enabled: boolean;
  /** null unless the publication is scheduled. */
  auto_publish_state: AutoPublishState | null;
  auto_publish_window_ends_at: string | null;
  auto_publish_error: AutoPublishError | null;
  /** What the user sees; computed only by the backend (post_display_state). */
  display_state: PostDisplayState;
  created_at: string;
  updated_at: string;
}

// Keep in sync with YouTubeConnectionStatus in backend/app/models.py
// ("not_connected" means the backend has no connection row).
export type YouTubeConnectionStatus =
  "not_connected" | "connected" | "reconnect_required";

export const YOUTUBE_CONNECTION_STATUS_LABELS: Record<
  YouTubeConnectionStatus,
  string
> = {
  not_connected: "Not connected",
  connected: "Connected",
  reconnect_required: "Reconnect required",
};

export interface YouTubeChannel {
  id: string;
  title: string;
  handle: string | null;
  thumbnail_url: string | null;
}

export interface YouTubeConnection {
  status: YouTubeConnectionStatus;
  channel: YouTubeChannel | null;
  connected_at: string | null;
  last_verified_at: string | null;
  oauth_configured: boolean;
}

// Keep in sync with AttemptStatus in backend/app/youtube_oauth.py.
export type OAuthAttemptStatus =
  | "pending"
  | "awaiting_confirmation"
  | "completed"
  | "failed"
  | "cancelled"
  | "expired";

export interface OAuthAttempt {
  attempt_id: string;
  account_id: number;
  status: OAuthAttemptStatus;
  expires_at: string;
  error: { code: string; message: string } | null;
  current_channel: YouTubeChannel | null;
  new_channel: YouTubeChannel | null;
  connection: YouTubeConnection | null;
}

export interface AuthorizeResult {
  attempt_id: string;
  authorization_url: string;
  expires_at: string;
}

// Keep in sync with InstagramAccountType in backend/app/models.py.
export type InstagramAccountType = "BUSINESS" | "MEDIA_CREATOR";

export const INSTAGRAM_ACCOUNT_TYPE_LABELS: Record<
  InstagramAccountType,
  string
> = {
  BUSINESS: "Business",
  MEDIA_CREATOR: "Creator",
};

// Keep in sync with InstagramConnectionStatus in backend/app/models.py
// ("not_connected" means the backend has no connection row).
export type InstagramConnectionStatus =
  "not_connected" | "connected" | "reconnect_required";

export const INSTAGRAM_CONNECTION_STATUS_LABELS: Record<
  InstagramConnectionStatus,
  string
> = {
  not_connected: "Not connected",
  connected: "Connected",
  reconnect_required: "Reconnect required",
};

export interface InstagramIdentity {
  instagram_user_id: string;
  username: string;
  account_type: InstagramAccountType;
  profile_picture_url: string | null;
}

export interface InstagramConnection {
  status: InstagramConnectionStatus;
  identity: InstagramIdentity | null;
  connected_at: string | null;
  last_verified_at: string | null;
  access_expires_at: string | null;
  oauth_configured: boolean;
}

// Keep in sync with InstagramAttemptStatus in backend/app/instagram_oauth.py.
export type InstagramOAuthAttemptStatus =
  | "pending"
  | "awaiting_confirmation"
  | "completed"
  | "failed"
  | "cancelled"
  | "expired";

export interface InstagramOAuthAttempt {
  attempt_id: string;
  account_id: number;
  status: InstagramOAuthAttemptStatus;
  expires_at: string;
  error: { code: string; message: string } | null;
  current_identity: InstagramIdentity | null;
  new_identity: InstagramIdentity | null;
  connection: InstagramConnection | null;
}

export interface InstagramAuthorizeResult {
  attempt_id: string;
  authorization_url: string;
  expires_at: string;
}

// Keep in sync with ThreadsConnectionStatus in backend/app/models.py
// ("not_connected" means the backend has no connection row).
export type ThreadsConnectionStatus =
  "not_connected" | "connected" | "reconnect_required";

export const THREADS_CONNECTION_STATUS_LABELS: Record<
  ThreadsConnectionStatus,
  string
> = {
  not_connected: "Not connected",
  connected: "Connected",
  reconnect_required: "Reconnect required",
};

export interface ThreadsIdentity {
  threads_user_id: string;
  username: string;
  display_name: string | null;
  profile_picture_url: string | null;
}

export interface ThreadsConnection {
  status: ThreadsConnectionStatus;
  identity: ThreadsIdentity | null;
  connected_at: string | null;
  last_verified_at: string | null;
  token_obtained_at: string | null;
  /** Expiry of the long-lived token (`credential_expires_at` in the backend). */
  access_expires_at: string | null;
  /** Last value reported by Meta; informational, it never changes the status. */
  data_access_expires_at: string | null;
  oauth_configured: boolean;
}

// Keep in sync with ThreadsAttemptStatus in backend/app/threads_oauth.py.
export type ThreadsOAuthAttemptStatus =
  | "pending"
  | "awaiting_confirmation"
  | "completed"
  | "failed"
  | "cancelled"
  | "expired";

export interface ThreadsOAuthAttempt {
  attempt_id: string;
  account_id: number;
  status: ThreadsOAuthAttemptStatus;
  expires_at: string;
  error: { code: string; message: string } | null;
  current_identity: ThreadsIdentity | null;
  new_identity: ThreadsIdentity | null;
  connection: ThreadsConnection | null;
}

export interface ThreadsAuthorizeResult {
  attempt_id: string;
  authorization_url: string;
  expires_at: string;
}

// Keep in sync with TikTokConnectionStatus in backend/app/models.py
// ("not_connected" means the backend has no connection row).
export type TikTokConnectionStatus =
  "not_connected" | "connected" | "reconnect_required";

export const TIKTOK_CONNECTION_STATUS_LABELS: Record<
  TikTokConnectionStatus,
  string
> = {
  not_connected: "Not connected",
  connected: "Connected",
  reconnect_required: "Reconnect required",
};

/** Keep in sync with TikTokIdentityRead in backend/app/schemas.py. */
export interface TikTokIdentity {
  open_id: string;
  display_name: string | null;
  avatar_url: string | null;
}

/**
 * What the granted scopes allow: Direct Post needs the base scopes, Upload to
 * Inbox needs `video.upload` as well. Keep in sync with TikTokCapabilitiesRead.
 */
export interface TikTokCapabilities {
  direct_post: boolean;
  inbox_upload: boolean;
}

/**
 * Requested scopes granted according to TikTok's last token response (exchange or
 * renewal); never a live check. Keep in sync with TikTokPermissionsRead.
 */
export interface TikTokPermissions {
  granted: string[];
  source: "token_exchange" | "token_refresh";
  confirmed_at: string;
  capabilities: TikTokCapabilities;
}

/** Keep in sync with TikTokConnectionRead in backend/app/schemas.py. */
export interface TikTokConnection {
  status: TikTokConnectionStatus;
  identity: TikTokIdentity | null;
  connected_at: string | null;
  last_verified_at: string | null;
  access_expires_at: string | null;
  refresh_expires_at: string | null;
  /** null when the stored credential cannot be read. */
  permissions: TikTokPermissions | null;
  oauth_configured: boolean;
}

// Keep in sync with TikTokAttemptStatus in backend/app/tiktok_oauth.py.
export type TikTokOAuthAttemptStatus =
  | "pending"
  | "processing"
  | "awaiting_confirmation"
  | "completed"
  | "failed"
  | "cancelled"
  | "expired";

/** Public identity shown in an attempt (no full open_id). */
export interface TikTokAttemptIdentity {
  display_name: string | null;
  avatar_url: string | null;
  open_id_suffix: string;
}

/** Keep in sync with TikTokOAuthAttemptRead in backend/app/schemas.py. */
export interface TikTokOAuthAttempt {
  attempt_id: string;
  account_id: number;
  status: TikTokOAuthAttemptStatus;
  expires_at: string;
  error: { code: string; message: string } | null;
  current_identity: TikTokAttemptIdentity | null;
  new_identity: TikTokAttemptIdentity | null;
  connection: TikTokConnection | null;
}

export interface TikTokAuthorizeResult {
  attempt_id: string;
  authorization_url: string;
  expires_at: string;
}

// Keep in sync with TikTokRevocation in backend/app/schemas.py.
export type TikTokRevocation =
  "revoked" | "already_invalid" | "not_revoked" | "not_connected";

export interface TikTokDisconnectResult {
  connection: TikTokConnection;
  revocation: TikTokRevocation;
}

// Keep in sync with TelegramConnectionStatus in backend/app/models.py
// ("not_connected" means the backend has no connection row).
export type TelegramConnectionStatus =
  "not_connected" | "connected" | "reconnect_required";

export const TELEGRAM_CONNECTION_STATUS_LABELS: Record<
  TelegramConnectionStatus,
  string
> = {
  not_connected: "Not connected",
  connected: "Connected",
  reconnect_required: "Reconnect required",
};

export interface TelegramIdentity {
  telegram_user_id: string;
  display_name: string;
  username: string | null;
}

/** A broadcast channel the account can post in; never carries an access hash. */
export interface TelegramChannel {
  channel_id: string;
  title: string;
  username: string | null;
}

export interface TelegramLogin {
  step: "code" | "password";
  /** Masked phone number; the full number is never returned. */
  phone_hint: string;
  expires_at: string;
}

export interface TelegramConnection {
  account_id: number;
  configured: boolean;
  status: TelegramConnectionStatus;
  identity: TelegramIdentity | null;
  channel: TelegramChannel | null;
  /** True while the account has Telegram publications scheduled or publishing. */
  channel_change_blocked: boolean;
  login: TelegramLogin | null;
  connected_at: string | null;
  last_verified_at: string | null;
  rate_limited_until: string | null;
}

// --- Analytics (Feature 027, contracts/analytics-api.md) -------------------------

/** "Not available" is `value: null, available: false`, never a 0. */
export interface MetricValue {
  name: string;
  label: string;
  value: number | null;
  available: boolean;
  origin: "public_counter" | "insight";
  concept: string | null;
  definition: string;
}

/** Derived by AutoPublisher with the platform's fixed formula; never stored. */
export interface Engagement {
  available: boolean;
  value: number | null;
  formula: string;
  components: Record<string, number | null>;
}

export type MetricRefreshStatus =
  | "pending"
  | "ok"
  | "stale"
  | "rate_limited"
  | "reconnect_required"
  | "permission_required"
  | "remote_not_found"
  | "remote_deleted";

export interface RefreshState {
  status: MetricRefreshStatus;
  last_success_at: string | null;
  last_attempt_at: string | null;
  next_attempt_at: string | null;
  manual_pending: boolean;
  error_code: string | null;
  error_message: string | null;
  cooldown_until: string | null;
}

export type CapabilityState =
  | "supported"
  | "permission_required"
  | "not_supported"
  | "not_available_on_platform"
  | "not_applicable"
  | "not_connected"
  | "reconnect_required";

export interface CapabilityGroup {
  group: string;
  state: Exclude<
    CapabilityState,
    "not_available_on_platform" | "not_applicable"
  >;
  missing_permission: string | null;
}

export interface MetricCapability {
  state: CapabilityState;
  groups: CapabilityGroup[];
  reason: string | null;
}

export interface AccountCapability {
  account_id: number;
  platform: Platform;
  label: string;
  capability: MetricCapability;
}

/** A post with its latest valid reading, as served outside a ranking. */
export type PublicationAnalyticsRead = Omit<PostAnalyticsRow, "ranked">;

export interface PostAnalyticsRow {
  publication_id: number;
  content_id: number | null;
  content_type: "image" | "video" | "text";
  title: string | null;
  platform: Platform;
  account_id: number;
  account_label: string;
  published_at: string;
  age_days: number;
  remote_url: string | null;
  link_state: "linked" | "not_linked";
  not_linked_reason: string | null;
  capability_state: CapabilityState;
  metrics: MetricValue[];
  engagement: Engagement | null;
  refresh: RefreshState | null;
  captured_at: string | null;
  /** Only in a ranking: false when the post lacks the sorted metric (never 0). */
  ranked: boolean | null;
}

/** One publication's own metric under a common concept (never comparable). */
export interface AlignedCell {
  publication_id: number;
  platform: Platform;
  account_id: number;
  /** The platform's original metric, or null if it has none for the concept. */
  metric_name: string | null;
  value: number | null;
  available: boolean;
  definition: string | null;
}

/**
 * One media's publications side by side. `aligned` only lines up likes and
 * comments visually; there are no totals, differences, ordering or "best".
 */
export interface ContentSideBySide {
  content_id: number;
  aligned: {
    concept: string;
    label: string;
    definition: string;
    cells: AlignedCell[];
  }[];
  per_platform: PublicationAnalyticsRead[];
  note: string;
}

/** Filters of the posts list. `sort` ranks within one platform only. */
export interface AnalyticsPostsQuery {
  platform?: Platform;
  account_id?: number;
  /** Inclusive UTC publication days, `YYYY-MM-DD`. */
  published_from?: string;
  published_to?: string;
  /** A metric name of `platform`, or `engagement`. */
  sort?: string;
  order?: "asc" | "desc";
}

/** A median over the posts that have the metric; null below 3 of them. */
export interface AnalyticsMedian {
  count: number;
  insufficient_sample: boolean;
  value: number | null;
}

/** One content type within one platform (never mixed across platforms). */
export interface ContentTypeSummary {
  content_type: "image" | "video" | "text";
  posts_total: number;
  posts_with_data: number;
  insufficient_sample: boolean;
  median_age_days: number | null;
  medians: (AnalyticsMedian & {
    name: string;
    label: string;
    concept: string | null;
  })[];
  engagement_median: AnalyticsMedian | null;
}

export interface ProjectRefreshResult {
  queued: number;
  in_cooldown: number;
  not_eligible: number;
}

export interface AnalyticsCatalog {
  concepts: {
    key: string;
    label: string;
    definition: string;
    alignable: boolean;
  }[];
  platforms: {
    platform: Platform;
    metrics: (Omit<MetricValue, "value" | "available"> & { group: string })[];
    excluded: { name: string; reason: string }[];
    engagement: { numerator: string[]; denominator: string } | null;
  }[];
}
