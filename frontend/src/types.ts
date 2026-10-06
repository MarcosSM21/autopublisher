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
export type PublicationStatus = "unscheduled" | "scheduled" | "cancelled";

export const PUBLICATION_STATUS_LABELS: Record<PublicationStatus, string> = {
  scheduled: "Scheduled",
  unscheduled: "Unscheduled",
  cancelled: "Cancelled",
};

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
  content_id: number;
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
  content: PublicationContentSummary;
  account: PublicationAccountSummary;
  project_active: boolean;
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
