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
  handle: string;
  display_name: string | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface FieldError {
  field: string;
  message: string;
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

/** Derived from the content's publications (never stored). */
export interface ContentUsage {
  used: boolean;
  publication_count: number;
  published_count: number;
  awaiting_count: number;
  scheduled_count: number;
  platforms: Platform[];
  last_published_at: string | null;
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
}

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

export const PUBLICATION_STATUS_LABELS: Record<PublicationStatus, string> = {
  publishing: "Publishing",
  awaiting_user_action: "Awaiting your action",
  failed: "Failed",
  scheduled: "Scheduled",
  unscheduled: "Unscheduled",
  published: "Published",
  cancelled: "Cancelled",
};

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

/** Why the last automatic start failed; safe code and message only. */
export interface AutoPublishError {
  code: string;
  message: string;
  failed_at: string;
}

/** Global automation status of the local scheduler. */
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
  /** Non-sensitive snapshot of what was sent (platform-specific keys). */
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

export const TIKTOK_MODE_LABELS: Record<TikTokMode, string> = {
  DIRECT_POST: "Direct Post",
  INBOX_UPLOAD: "Upload to Inbox",
};

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

/**
 * Platforms that accept publications without media (text posts). Mirrors the
 * backend publisher capability `accepts_text_only` and must be kept aligned with
 * it: only the registered Threads publisher declares it today.
 */
export const TEXT_POST_PLATFORMS: Platform[] = ["threads", "telegram"];

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
  handle: string;
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
