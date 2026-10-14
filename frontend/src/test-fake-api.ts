// In-memory stand-in for the backend API used by UI tests (see contracts/api.md).
import { vi } from "vitest";
import type {
  Account,
  AttemptTrigger,
  AutomationStatus,
  AutoPublishState,
  Content,
  ImportItemResult,
  InstagramConnection,
  InstagramIdentity,
  InstagramOAuthAttempt,
  InstagramPublicationOptions,
  MediaFormat,
  OAuthAttempt,
  Project,
  Publication,
  PublicationAttempt,
  PublishCheck,
  ThreadsConnection,
  ThreadsIdentity,
  ThreadsOAuthAttempt,
  ThreadsPublicationOptions,
  TikTokAttemptIdentity,
  TikTokConnection,
  TikTokIdentity,
  TikTokOAuthAttempt,
  YouTubeChannel,
  YouTubeConnection,
  YouTubePublicationOptions,
} from "./types.ts";

/** What a pending OAuth attempt becomes the first time it is polled. */
export type AttemptOutcome =
  | { status: "completed"; channel: YouTubeChannel }
  | { status: "failed"; code: string; message: string }
  | { status: "awaiting_confirmation"; channel: YouTubeChannel }
  | { status: "expired" }
  | { status: "not_found" };

export const CHANNEL: YouTubeChannel = {
  id: "UC_TEST_1",
  title: "Cyber Channel",
  handle: "@cyberchannel",
  thumbnail_url: null,
};

export const IG_IDENTITY: InstagramIdentity = {
  instagram_user_id: "17841400000000001",
  username: "cyber.studio",
  account_type: "BUSINESS",
  profile_picture_url: null,
};

export const IG_REDIRECT_URI =
  "https://localhost/autopublisher/instagram/callback";

export const TH_IDENTITY: ThreadsIdentity = {
  threads_user_id: "25841234567890123",
  username: "cyber.studio",
  display_name: "Cyber Studio",
  profile_picture_url: null,
};

export const TH_REDIRECT_URI =
  "https://localhost/autopublisher/threads/callback";

/** Default external URL of a successful attempt, per platform. */
const EXTERNAL_URLS: Partial<Record<Account["platform"], string>> = {
  youtube: "https://www.youtube.com/watch?v=FakeVid_001",
  instagram: "https://www.instagram.com/p/FakePost001/",
  threads: "https://www.threads.com/@cyber.studio/post/FakePost001",
};

export const TT_IDENTITY: TikTokIdentity = {
  open_id: "-000fake-tt-open-id-7d1c3e",
  display_name: "Cyber Studio",
  avatar_url: "https://p16-sign.tiktokcdn.example/avatar.jpeg",
};

/** What a pending (or processing) TikTok attempt becomes when it is polled. */
export type TikTokAttemptOutcome =
  | { status: "completed"; identity: TikTokIdentity }
  | { status: "failed"; code: string; message: string }
  | { status: "awaiting_confirmation"; identity: TikTokIdentity }
  | { status: "processing" }
  | { status: "expired" }
  | { status: "not_found" };

/** An error answered by the fake TikTok endpoints. */
export interface TikTokFakeError {
  status: number;
  code: string;
  message: string;
}

/** What `disconnect` answers for a connected TikTok account. */
export type TikTokDisconnectOutcome =
  "revoked" | "already_invalid" | TikTokFakeError;

function tiktokAttemptIdentity(
  identity: TikTokIdentity,
): TikTokAttemptIdentity {
  return {
    display_name: identity.display_name,
    avatar_url: identity.avatar_url,
    open_id_suffix: identity.open_id.slice(-6),
  };
}

/** What completing a pending Threads attempt produces. */
export type ThreadsCompleteOutcome =
  | { status: "completed"; identity: ThreadsIdentity }
  | { status: "awaiting_confirmation"; identity: ThreadsIdentity };

/** What completing a pending Instagram attempt produces. */
export type InstagramCompleteOutcome =
  | { status: "completed"; identity: InstagramIdentity }
  | { status: "awaiting_confirmation"; identity: InstagramIdentity };

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
  | "published_at"
  | "auto_publish_enabled"
  | "auto_publish_error"
  | "created_at"
  | "updated_at"
>;

/** Automatic window after scheduled_at, like AUTO_PUBLISH_WINDOW in the backend. */
const WINDOW_MS = 10 * 60 * 1000;

type StoredOptions = Omit<YouTubePublicationOptions, "complete" | "editable">;

interface StoredInstagramOptions {
  is_ai_generated: boolean | null;
  share_to_feed: boolean;
  alt_text: string | null;
}

const DEFAULT_INSTAGRAM_OPTIONS: StoredInstagramOptions = {
  is_ai_generated: null,
  share_to_feed: true,
  alt_text: null,
};

const DEFAULT_OPTIONS: StoredOptions = {
  privacy_status: "private",
  made_for_kids: null,
  contains_synthetic_media: null,
  notify_subscribers: false,
};

/** Publication statuses that never block a new publication of the same pair. */
const HISTORY_STATUSES = ["cancelled", "published"];

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
  /** YouTube connections by account id (absent = not connected). */
  connections = new Map<number, Omit<YouTubeConnection, "oauth_configured">>();
  oauthConfigured = true;
  attempts = new Map<string, OAuthAttempt>();
  nextAttemptOutcome: AttemptOutcome = {
    status: "completed",
    channel: CHANNEL,
  };
  /** Instagram connections by account id (absent = not connected). */
  instagramConnections = new Map<
    number,
    Omit<InstagramConnection, "oauth_configured">
  >();
  instagramConfigured = true;
  instagramAttempts = new Map<string, InstagramOAuthAttempt>();
  nextInstagramOutcome: InstagramCompleteOutcome = {
    status: "completed",
    identity: IG_IDENTITY,
  };
  /** Threads connections by account id (absent = not connected). */
  threadsConnections = new Map<
    number,
    Omit<ThreadsConnection, "oauth_configured">
  >();
  threadsConfigured = true;
  threadsAttempts = new Map<string, ThreadsOAuthAttempt>();
  nextThreadsOutcome: ThreadsCompleteOutcome = {
    status: "completed",
    identity: TH_IDENTITY,
  };
  /** TikTok connections by account id (absent = not connected). */
  tiktokConnections = new Map<
    number,
    Omit<TikTokConnection, "oauth_configured">
  >();
  tiktokConfigured = true;
  tiktokAttempts = new Map<string, TikTokOAuthAttempt>();
  nextTikTokOutcome: TikTokAttemptOutcome = {
    status: "completed",
    identity: TT_IDENTITY,
  };
  /** Identity waiting for confirmation, by attempt id. */
  tiktokPendingIdentities = new Map<string, TikTokIdentity>();
  /** When set, `verify` answers this error. */
  tiktokVerifyError: TikTokFakeError | null = null;
  nextTikTokDisconnect: TikTokDisconnectOutcome = "revoked";
  /** When set, each import request waits for it before answering. */
  importGate: (() => Promise<void>) | null = null;
  /** YouTube options by publication id (absent = defaults). */
  youtubeOptions = new Map<number, StoredOptions>();
  /** Instagram options by publication id (absent = defaults). */
  instagramOptions = new Map<number, StoredInstagramOptions>();
  /** Stored Threads alt text by publication id (no entry = none). */
  threadsAltTexts = new Map<number, string | null>();
  threadsDeliveryConfigured = true;
  instagramDeliveryConfigured = true;
  /**
   * Publications whose uncertain last attempt the next publish check settles as
   * published (the backend's read-only reconciliation).
   */
  reconcileOnCheck = new Set<number>();
  /** Overrides of the computed publish check, by publication id. */
  publishChecks = new Map<number, Partial<PublishCheck>>();
  /** Attempts by publication id, oldest first. */
  publicationAttempts = new Map<number, PublicationAttempt[]>();
  /** Global automation status (GET/PUT /automation). */
  automation: AutomationStatus = {
    paused: false,
    running: true,
    last_check_at: TIMESTAMP,
    check_interval_seconds: 30,
    window_minutes: 10,
  };
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
    const content = this.contents.find((c) => c.id === values.content_id);
    const account = this.accounts.find((a) => a.id === values.account_id)!;
    const record: PublicationRecord = {
      id: this.nextId++,
      project_id: content?.project_id ?? account.project_id,
      status: values.scheduled_at ? "scheduled" : "unscheduled",
      scheduled_at: null,
      title_override: null,
      description_override: null,
      hashtags_override: null,
      published_at: null,
      auto_publish_enabled: false,
      auto_publish_error: null,
      created_at: TIMESTAMP,
      updated_at: TIMESTAMP,
      ...values,
    };
    this.publications.push(record);
    return this.publicationView(record);
  }

  /** Builds the API representation, like publication_to_read in the backend. */
  publicationView(record: PublicationRecord): Publication {
    const content = this.contents.find((c) => c.id === record.content_id);
    const account = this.accounts.find((a) => a.id === record.account_id)!;
    const project = this.projects.find((p) => p.id === record.project_id)!;
    const attempts = this.publicationAttempts.get(record.id) ?? [];
    const scheduled = record.status === "scheduled" && record.scheduled_at;
    return {
      ...record,
      latest_attempt: attempts.at(-1) ?? null,
      attempt_count: attempts.length,
      auto_publish_state: this.autoPublishState(record),
      auto_publish_window_ends_at: scheduled
        ? new Date(
            new Date(record.scheduled_at!).getTime() + WINDOW_MS,
          ).toISOString()
        : null,
      // Without content, only the publication's own values exist.
      title: record.title_override ?? content?.title ?? null,
      description: record.description_override ?? content?.description ?? null,
      hashtags: record.hashtags_override ?? content?.hashtags ?? [],
      content: content
        ? {
            id: content.id,
            title: content.title,
            original_filename: content.original_filename,
            media_type: content.media_type,
            file_url: content.file_url,
            file_available: content.file_available,
          }
        : null,
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

  /** Like auto_publish_state in backend/app/automation.py, with the current time. */
  autoPublishState(record: PublicationRecord): AutoPublishState | null {
    if (record.status !== "scheduled" || !record.scheduled_at) {
      return null;
    }
    if (!record.auto_publish_enabled) {
      return "disabled";
    }
    const at = new Date(record.scheduled_at).getTime();
    const now = Date.now();
    if (now > at + WINDOW_MS) {
      return "overdue";
    }
    if (this.automation.paused) {
      return "paused";
    }
    return now < at ? "waiting" : "due";
  }

  /** Test control: the scheduler started the publication on its own. */
  startScheduledAttempt(publicationId: number): void {
    const record = this.publications.find((p) => p.id === publicationId)!;
    this.startAttempt(record, "scheduled");
  }

  setConnection(
    accountId: number,
    channel: YouTubeChannel = CHANNEL,
    status: "connected" | "reconnect_required" = "connected",
  ): void {
    this.connections.set(accountId, {
      status,
      channel,
      connected_at: TIMESTAMP,
      last_verified_at: TIMESTAMP,
    });
  }

  optionsView(record: PublicationRecord): YouTubePublicationOptions {
    const stored = this.youtubeOptions.get(record.id) ?? DEFAULT_OPTIONS;
    return {
      ...stored,
      complete:
        stored.made_for_kids !== null &&
        stored.contains_synthetic_media !== null,
      editable: ["unscheduled", "scheduled", "failed"].includes(record.status),
    };
  }

  instagramCaption(record: PublicationRecord): string {
    const content = this.contents.find((c) => c.id === record.content_id)!;
    const description = record.description_override ?? content.description;
    const hashtags = record.hashtags_override ?? content.hashtags;
    const tags = hashtags.map((tag) => `#${tag}`).join(" ");
    return [description ?? "", tags].filter(Boolean).join("\n\n");
  }

  instagramOptionsView(record: PublicationRecord): InstagramPublicationOptions {
    const content = this.contents.find((c) => c.id === record.content_id)!;
    const stored =
      this.instagramOptions.get(record.id) ?? DEFAULT_INSTAGRAM_OPTIONS;
    const kind = content.media_type === "video" ? "reel" : "image";
    const caption = this.instagramCaption(record);
    const problems: InstagramPublicationOptions["problems"] = [];
    if (stored.is_ai_generated === null) {
      problems.push({
        code: "instagram_options_incomplete",
        message: "Declare whether the content is AI-generated.",
        field: "is_ai_generated",
      });
    }
    if (!this.instagramDeliveryConfigured) {
      problems.push({
        code: "media_delivery_not_configured",
        message: "Temporary media delivery is not configured.",
        field: null,
      });
    }
    return {
      media_kind: kind,
      caption,
      caption_length: caption.length,
      caption_hashtags: (caption.match(/(?<!\w)#\w/g) ?? []).length,
      caption_mentions: (caption.match(/(?<!\w)@[\w.]/g) ?? []).length,
      is_ai_generated: stored.is_ai_generated,
      share_to_feed: kind === "reel" ? stored.share_to_feed : null,
      alt_text: kind === "image" ? stored.alt_text : null,
      complete: stored.is_ai_generated !== null,
      editable: ["unscheduled", "scheduled", "failed"].includes(record.status),
      media_delivery_configured: this.instagramDeliveryConfigured,
      problems,
      limits: {
        caption_characters: 2200,
        caption_hashtags: 30,
        caption_mentions: 20,
        alt_text_characters: 1000,
      },
    };
  }

  /** The backend's read-only reconciliation of an uncertain last attempt. */
  private reconcile(record: PublicationRecord): void {
    if (!this.reconcileOnCheck.has(record.id) || record.status !== "failed") {
      return;
    }
    const attempt = this.publicationAttempts.get(record.id)?.at(-1);
    if (!attempt?.requires_manual_review) {
      return;
    }
    this.reconcileOnCheck.delete(record.id);
    Object.assign(attempt, {
      status: "succeeded",
      stage: "done",
      error: null,
      outcome_determined: true,
      requires_manual_review: false,
      external_id: null,
      external_url: null,
      warnings: [
        {
          code: "remote_identity_unavailable",
          message:
            "Instagram confirmed the post was published but did not return its ID.",
        },
      ],
    });
    Object.assign(record, {
      status: "published",
      published_at: LATER,
      updated_at: LATER,
    });
  }

  /** Simplified preflight; tests override it with `publishChecks`. */
  publishCheckView(record: PublicationRecord): PublishCheck {
    this.reconcile(record);
    const content = this.contents.find((c) => c.id === record.content_id)!;
    const account = this.accounts.find((a) => a.id === record.account_id)!;
    if (account.platform === "instagram") {
      return this.instagramCheckView(record);
    }
    if (account.platform === "threads") {
      return this.threadsCheckView(record);
    }
    const options = this.optionsView(record);
    const problems: PublishCheck["problems"] = [];
    if (!["unscheduled", "scheduled", "failed"].includes(record.status)) {
      problems.push({
        code: "publication_not_eligible",
        message: "This publication cannot be published in its current state.",
        field: null,
      });
    }
    if (account.platform !== "youtube") {
      problems.push({
        code: "platform_not_supported",
        message: "Publishing is not available for this platform yet.",
        field: null,
      });
    }
    if (content.media_type !== "video") {
      problems.push({
        code: "content_not_video",
        message: "YouTube only accepts video content.",
        field: null,
      });
    }
    if (!options.complete) {
      problems.push({
        code: "youtube_options_incomplete",
        message:
          "Declare whether the video is made for kids and whether it contains altered or synthetic content.",
        field: null,
      });
    }
    const latest = this.publicationAttempts.get(record.id)?.at(-1);
    const check: PublishCheck = {
      eligible: problems.length === 0,
      problems,
      requires_remote_check: latest?.requires_manual_review ?? false,
      summary: [
        {
          label: "Title",
          value: record.title_override ?? content.title ?? "",
        },
        { label: "Channel", value: `${CHANNEL.title} (${CHANNEL.id})` },
        { label: "Privacy", value: options.privacy_status },
        {
          label: "Notify subscribers",
          value: options.notify_subscribers ? "Yes" : "No",
        },
        { label: "File", value: content.original_filename },
      ],
      scheduled_at: record.status === "scheduled" ? record.scheduled_at : null,
    };
    const override = this.publishChecks.get(record.id);
    if (override) {
      Object.assign(check, override);
      check.eligible = override.eligible ?? check.problems.length === 0;
    }
    return check;
  }

  /** The exact text a Threads publication sends (description + hashtags). */
  threadsText(record: PublicationRecord): string {
    const view = this.publicationView(record);
    const tags = view.hashtags.map((tag) => `#${tag}`).join(" ");
    return [view.description ?? "", tags].filter(Boolean).join("\n\n");
  }

  /** Like options_to_read in backend/app/threads_publishing.py (simplified). */
  threadsOptionsView(record: PublicationRecord): ThreadsPublicationOptions {
    const content = this.contents.find((c) => c.id === record.content_id);
    const kind = content ? content.media_type : "text";
    const text = this.threadsText(record);
    // Conservative count: characters outside the BMP count as 4.
    const length = [...text].reduce(
      (total, char) => total + (char.codePointAt(0)! > 0xffff ? 4 : 1),
      0,
    );
    const links = new Set(text.match(/(?:https?:\/\/|www\.)\S+/gi) ?? []).size;
    const problems: ThreadsPublicationOptions["problems"] = [];
    if (kind === "text" && !text.trim()) {
      problems.push({
        code: "threads_text_invalid",
        message: "A text post needs a text: write a description or hashtags.",
        field: "text",
      });
    }
    if (length > 500) {
      problems.push({
        code: "threads_text_invalid",
        message: `The text has ${length} characters (emoji count as several); Threads accepts at most 500.`,
        field: "text",
      });
    }
    if (links > 5) {
      problems.push({
        code: "threads_text_invalid",
        message: `The text has ${links} links; Threads accepts at most 5.`,
        field: "text",
      });
    }
    if (kind !== "text" && !this.threadsDeliveryConfigured) {
      problems.push({
        code: "media_delivery_not_configured",
        message: "Temporary media delivery is not configured.",
        field: null,
      });
    }
    return {
      media_kind: kind,
      text,
      text_length: length,
      text_links: links,
      alt_text:
        kind === "text" ? null : (this.threadsAltTexts.get(record.id) ?? null),
      editable: ["unscheduled", "scheduled", "failed"].includes(record.status),
      media_delivery_required: kind !== "text",
      media_delivery_configured: this.threadsDeliveryConfigured,
      problems,
      limits: {
        text_characters: 500,
        text_links: 5,
        alt_text_characters: 1000,
      },
    };
  }

  private threadsCheckView(record: PublicationRecord): PublishCheck {
    const problems: PublishCheck["problems"] = [];
    if (!["unscheduled", "scheduled", "failed"].includes(record.status)) {
      problems.push({
        code: "publication_not_eligible",
        message: "This publication cannot be published in its current state.",
        field: null,
      });
    }
    const latest = this.publicationAttempts.get(record.id)?.at(-1);
    const text = this.threadsText(record);
    const check: PublishCheck = {
      eligible: problems.length === 0,
      problems,
      requires_remote_check:
        record.status === "failed" && (latest?.requires_manual_review ?? false),
      summary: [
        {
          label: "Post type",
          value: record.content_id === null ? "Text" : "Image",
        },
        {
          label: "Threads account",
          value: `${TH_IDENTITY.username} (${TH_IDENTITY.threads_user_id})`,
        },
        { label: "Text", value: text || "(empty)" },
      ],
      scheduled_at: record.status === "scheduled" ? record.scheduled_at : null,
    };
    const override = this.publishChecks.get(record.id);
    if (override) {
      Object.assign(check, override);
      check.eligible = override.eligible ?? check.problems.length === 0;
    }
    return check;
  }

  private instagramCheckView(record: PublicationRecord): PublishCheck {
    const options = this.instagramOptionsView(record);
    const problems: PublishCheck["problems"] = [];
    if (!["unscheduled", "scheduled", "failed"].includes(record.status)) {
      problems.push({
        code: "publication_not_eligible",
        message: "This publication cannot be published in its current state.",
        field: null,
      });
    }
    problems.push(...options.problems);
    const latest = this.publicationAttempts.get(record.id)?.at(-1);
    const check: PublishCheck = {
      eligible: problems.length === 0,
      problems,
      requires_remote_check:
        record.status === "failed" && (latest?.requires_manual_review ?? false),
      summary: [
        {
          label: "Post type",
          value: options.media_kind === "reel" ? "Reel" : "Image Post",
        },
        { label: "Caption", value: options.caption },
      ],
      scheduled_at: record.status === "scheduled" ? record.scheduled_at : null,
    };
    const override = this.publishChecks.get(record.id);
    if (override) {
      Object.assign(check, override);
      check.eligible = override.eligible ?? check.problems.length === 0;
    }
    return check;
  }

  /** Test control: the running attempt entered another stage. */
  setStage(publicationId: number, stage: PublicationAttempt["stage"]): void {
    this.latestAttempt(publicationId).stage = stage;
  }

  /** Test control: the running upload of a publication sent more bytes. */
  progressAttempt(publicationId: number, bytesSent: number): void {
    const attempt = this.latestAttempt(publicationId);
    attempt.bytes_sent = bytesSent;
    attempt.stage = "uploading";
    attempt.progress = bytesSent / attempt.total_bytes;
  }

  /** Test control: the running upload finished successfully. */
  succeedAttempt(
    publicationId: number,
    values: {
      externalUrl?: string | null;
      privacy?: string;
      processing?: string;
      warnings?: PublicationAttempt["warnings"];
    } = {},
  ): void {
    const attempt = this.latestAttempt(publicationId);
    const record = this.publications.find((p) => p.id === publicationId)!;
    Object.assign(attempt, {
      status: "succeeded",
      stage: "done",
      finished_at: LATER,
      bytes_sent: attempt.total_bytes,
      progress: 1,
      outcome_determined: true,
      external_id: values.externalUrl === null ? null : "FakeVid_001",
      external_url:
        values.externalUrl === undefined
          ? EXTERNAL_URLS[attempt.platform]
          : values.externalUrl,
      details: {
        privacy_status: values.privacy ?? "private",
        ...(values.processing ? { processing_status: values.processing } : {}),
      },
      warnings: values.warnings ?? [],
    });
    Object.assign(record, {
      status: "published",
      published_at: LATER,
      updated_at: LATER,
    });
  }

  /** Test control: the running upload failed. */
  failAttempt(
    publicationId: number,
    code: string,
    message: string,
    determined = true,
  ): void {
    const attempt = this.latestAttempt(publicationId);
    const record = this.publications.find((p) => p.id === publicationId)!;
    Object.assign(attempt, {
      status: "failed",
      finished_at: LATER,
      error: { code, message },
      outcome_determined: determined,
      requires_manual_review: !determined,
    });
    Object.assign(record, { status: "failed", updated_at: LATER });
  }

  private latestAttempt(publicationId: number): PublicationAttempt {
    return this.publicationAttempts.get(publicationId)!.at(-1)!;
  }

  startAttempt(
    record: PublicationRecord,
    trigger: AttemptTrigger = "manual",
  ): void {
    const content = this.contents.find((c) => c.id === record.content_id);
    const account = this.accounts.find((a) => a.id === record.account_id)!;
    const options = this.optionsView(record);
    const attempts = this.publicationAttempts.get(record.id) ?? [];
    const submitted =
      account.platform === "threads"
        ? {
            media_kind: content ? content.media_type : "text",
            text: this.threadsText(record),
            threads_user_id: TH_IDENTITY.threads_user_id,
            username: TH_IDENTITY.username,
          }
        : account.platform === "instagram" && content
          ? {
              media_kind: content.media_type === "video" ? "reel" : "image",
              caption: this.instagramCaption(record),
              username: IG_IDENTITY.username,
            }
          : {
              title: record.title_override ?? content?.title ?? null,
              privacy_status: options.privacy_status,
              channel_id: CHANNEL.id,
              channel_title: CHANNEL.title,
            };
    attempts.push({
      id: this.nextId++,
      publication_id: record.id,
      platform: account.platform,
      trigger,
      status: "running",
      stage: "preparing",
      started_at: LATER,
      finished_at: null,
      bytes_sent: 0,
      total_bytes: content?.size_bytes ?? 0,
      progress: 0,
      error: null,
      outcome_determined: null,
      requires_manual_review: false,
      external_id: null,
      external_url: null,
      submitted,
      details: {},
      warnings: [],
    });
    this.publicationAttempts.set(record.id, attempts);
    Object.assign(record, {
      status: "publishing",
      auto_publish_enabled: false,
      auto_publish_error: null,
      updated_at: LATER,
    });
  }

  connectionView(accountId: number): YouTubeConnection {
    const stored = this.connections.get(accountId);
    return {
      status: "not_connected",
      channel: null,
      connected_at: null,
      last_verified_at: null,
      ...stored,
      oauth_configured: this.oauthConfigured,
    };
  }

  setInstagramConnection(
    accountId: number,
    identity: InstagramIdentity = IG_IDENTITY,
    status: "connected" | "reconnect_required" = "connected",
  ): void {
    this.instagramConnections.set(accountId, {
      status,
      identity,
      connected_at: TIMESTAMP,
      last_verified_at: TIMESTAMP,
      access_expires_at: "2026-12-04T10:00:00Z",
    });
  }

  instagramConnectionView(accountId: number): InstagramConnection {
    const stored = this.instagramConnections.get(accountId);
    return {
      status: "not_connected",
      identity: null,
      connected_at: null,
      last_verified_at: null,
      access_expires_at: null,
      ...stored,
      oauth_configured: this.instagramConfigured,
    };
  }

  setThreadsConnection(
    accountId: number,
    identity: ThreadsIdentity = TH_IDENTITY,
    status: "connected" | "reconnect_required" = "connected",
  ): void {
    this.threadsConnections.set(accountId, {
      status,
      identity,
      connected_at: TIMESTAMP,
      last_verified_at: TIMESTAMP,
      token_obtained_at: TIMESTAMP,
      access_expires_at: "2026-12-04T10:00:00Z",
      data_access_expires_at: "2027-01-03T10:00:00Z",
    });
  }

  threadsConnectionView(accountId: number): ThreadsConnection {
    const stored = this.threadsConnections.get(accountId);
    return {
      status: "not_connected",
      identity: null,
      connected_at: null,
      last_verified_at: null,
      token_obtained_at: null,
      access_expires_at: null,
      data_access_expires_at: null,
      ...stored,
      oauth_configured: this.threadsConfigured,
    };
  }

  setTikTokConnection(
    accountId: number,
    identity: TikTokIdentity = TT_IDENTITY,
    status: "connected" | "reconnect_required" = "connected",
  ): void {
    this.tiktokConnections.set(accountId, {
      status,
      identity,
      connected_at: TIMESTAMP,
      last_verified_at: TIMESTAMP,
      access_expires_at: "2026-10-06T10:00:00Z",
      refresh_expires_at: "2027-10-05T10:00:00Z",
      permissions: {
        granted: ["user.info.basic", "video.publish"],
        source: "token_exchange",
        confirmed_at: TIMESTAMP,
      },
    });
  }

  tiktokConnectionView(accountId: number): TikTokConnection {
    const stored = this.tiktokConnections.get(accountId);
    return {
      status: "not_connected",
      identity: null,
      connected_at: null,
      last_verified_at: null,
      access_expires_at: null,
      refresh_expires_at: null,
      permissions: null,
      ...stored,
      oauth_configured: this.tiktokConfigured,
    };
  }

  /** Simplified TikTok connection rules: see 012 contracts/api.md. */
  private handleTikTok(path: string, method: string): Response | null {
    let match: RegExpMatchArray | null;
    if (
      (match = path.match(/^\/accounts\/(\d+)\/tiktok-connection(\/[\w-]+)?$/))
    ) {
      const account = this.accounts.find((a) => a.id === Number(match![1]));
      if (!account) {
        return json(404, errorBody("not_found", "Account not found."));
      }
      if (account.platform !== "tiktok") {
        return json(
          409,
          errorBody(
            "platform_not_supported",
            "Only TikTok accounts can be connected.",
          ),
        );
      }
      const action = match[2];
      if (!action && method === "GET") {
        return json(200, this.tiktokConnectionView(account.id));
      }
      const project = this.projects.find((p) => p.id === account.project_id)!;
      if (action === "/authorize" && method === "POST") {
        if (!project.is_active) {
          return json(
            409,
            errorBody(
              "project_inactive",
              "Reactivate the project before connecting accounts.",
            ),
          );
        }
        if (!account.is_active) {
          return json(
            409,
            errorBody(
              "account_inactive",
              "Reactivate the account before connecting it.",
            ),
          );
        }
        if (!this.tiktokConfigured) {
          return json(
            503,
            errorBody(
              "tiktok_oauth_not_configured",
              "TikTok integration is not configured. See docs/tiktok-accounts.md.",
            ),
          );
        }
        for (const previous of this.tiktokAttempts.values()) {
          if (
            previous.account_id === account.id &&
            previous.status === "pending"
          ) {
            previous.status = "expired";
          }
        }
        const current = this.tiktokConnections.get(account.id)?.identity;
        const attempt: TikTokOAuthAttempt = {
          attempt_id: `tt-attempt-${this.nextId++}`,
          account_id: account.id,
          status: "pending",
          expires_at: LATER,
          error: null,
          current_identity: current ? tiktokAttemptIdentity(current) : null,
          new_identity: null,
          connection: null,
        };
        this.tiktokAttempts.set(attempt.attempt_id, attempt);
        return json(201, {
          attempt_id: attempt.attempt_id,
          authorization_url: `https://www.tiktok.com/v2/auth/authorize/?state=${attempt.attempt_id}`,
          expires_at: attempt.expires_at,
        });
      }
      const stored = this.tiktokConnections.get(account.id);
      if (action === "/verify" && method === "POST") {
        if (!project.is_active || !account.is_active) {
          return json(
            409,
            errorBody(
              project.is_active ? "account_inactive" : "project_inactive",
              "Reactivate it first.",
            ),
          );
        }
        if (!stored) {
          return json(
            409,
            errorBody(
              "tiktok_not_connected",
              "This TikTok account is not connected.",
            ),
          );
        }
        const failure = this.tiktokVerifyError;
        if (failure) {
          if (
            ["tiktok_reconnect_required", "tiktok_identity_mismatch"].includes(
              failure.code,
            )
          ) {
            stored.status = "reconnect_required";
          }
          return json(failure.status, errorBody(failure.code, failure.message));
        }
        stored.last_verified_at = LATER;
        return json(200, this.tiktokConnectionView(account.id));
      }
      if (
        (action === "/disconnect" || action === "/remove-local") &&
        method === "POST"
      ) {
        if (!stored) {
          return json(200, {
            connection: this.tiktokConnectionView(account.id),
            revocation: "not_connected",
          });
        }
        const outcome =
          action === "/remove-local"
            ? "not_revoked"
            : this.nextTikTokDisconnect;
        if (typeof outcome !== "string") {
          return json(outcome.status, errorBody(outcome.code, outcome.message));
        }
        this.tiktokConnections.delete(account.id);
        return json(200, {
          connection: this.tiktokConnectionView(account.id),
          revocation: outcome,
        });
      }
    }
    if ((match = path.match(/^\/tiktok\/oauth\/attempts\/([\w-]+)(\/\w+)?$/))) {
      const attempt = this.tiktokAttempts.get(match[1]);
      const notFound = json(
        404,
        errorBody(
          "tiktok_oauth_attempt_not_found",
          "This authorization was not found.",
        ),
      );
      if (!attempt) {
        return notFound;
      }
      const action = match[2];
      if (!action && method === "GET") {
        if (attempt.status === "pending" || attempt.status === "processing") {
          const outcome = this.nextTikTokOutcome;
          if (outcome.status === "not_found") {
            this.tiktokAttempts.delete(attempt.attempt_id);
            return notFound;
          }
          if (outcome.status === "completed") {
            this.setTikTokConnection(attempt.account_id, outcome.identity);
            attempt.connection = this.tiktokConnectionView(attempt.account_id);
          } else if (outcome.status === "awaiting_confirmation") {
            attempt.new_identity = tiktokAttemptIdentity(outcome.identity);
            this.tiktokPendingIdentities.set(
              attempt.attempt_id,
              outcome.identity,
            );
          } else if (outcome.status === "failed") {
            attempt.error = { code: outcome.code, message: outcome.message };
          }
          attempt.status = outcome.status;
        }
        return json(200, attempt);
      }
      if (action === "/confirm" && method === "POST") {
        const identity = this.tiktokPendingIdentities.get(attempt.attempt_id);
        if (attempt.status !== "awaiting_confirmation" || !identity) {
          return json(
            409,
            errorBody(
              "tiktok_oauth_attempt_not_confirmable",
              "This authorization can no longer be changed.",
            ),
          );
        }
        this.tiktokPendingIdentities.delete(attempt.attempt_id);
        this.setTikTokConnection(attempt.account_id, identity);
        attempt.status = "completed";
        attempt.connection = this.tiktokConnectionView(attempt.account_id);
        return json(200, attempt);
      }
      if (action === "/cancel" && method === "POST") {
        if (
          !["pending", "awaiting_confirmation", "cancelled"].includes(
            attempt.status,
          )
        ) {
          return json(
            409,
            errorBody(
              "tiktok_oauth_attempt_not_confirmable",
              "This authorization can no longer be changed.",
            ),
          );
        }
        attempt.status = "cancelled";
        return json(200, attempt);
      }
    }
    return null;
  }

  /** Simplified Threads connection rules: see 010 contracts/api.md. */
  private handleThreads(
    path: string,
    method: string,
    body: unknown,
  ): Response | null {
    let match: RegExpMatchArray | null;
    if (
      (match = path.match(/^\/accounts\/(\d+)\/threads-connection(\/\w+)?$/))
    ) {
      const account = this.accounts.find((a) => a.id === Number(match![1]));
      if (!account) {
        return json(404, errorBody("not_found", "Account not found."));
      }
      if (account.platform !== "threads") {
        return json(
          409,
          errorBody(
            "platform_not_supported",
            "Only Threads accounts can be connected.",
          ),
        );
      }
      const action = match[2];
      if (!action && method === "GET") {
        return json(200, this.threadsConnectionView(account.id));
      }
      const project = this.projects.find((p) => p.id === account.project_id)!;
      const inactive = !project.is_active
        ? json(
            409,
            errorBody(
              "project_inactive",
              "Reactivate the project before connecting accounts.",
            ),
          )
        : !account.is_active
          ? json(
              409,
              errorBody(
                "account_inactive",
                "Reactivate the account before connecting it.",
              ),
            )
          : null;
      if (action === "/authorize" && method === "POST") {
        if (inactive) {
          return inactive;
        }
        if (!this.threadsConfigured) {
          return json(
            503,
            errorBody(
              "threads_oauth_not_configured",
              "Threads integration is not configured. See docs/threads-accounts.md.",
            ),
          );
        }
        for (const previous of this.threadsAttempts.values()) {
          if (
            previous.account_id === account.id &&
            previous.status === "pending"
          ) {
            previous.status = "expired";
          }
        }
        const attempt: ThreadsOAuthAttempt = {
          attempt_id: `th-attempt-${this.nextId++}`,
          account_id: account.id,
          status: "pending",
          expires_at: LATER,
          error: null,
          current_identity:
            this.threadsConnections.get(account.id)?.identity ?? null,
          new_identity: null,
          connection: null,
        };
        this.threadsAttempts.set(attempt.attempt_id, attempt);
        return json(201, {
          attempt_id: attempt.attempt_id,
          authorization_url: `https://threads.com/oauth/authorize?state=${attempt.attempt_id}`,
          expires_at: attempt.expires_at,
        });
      }
      if (action === "/verify" && method === "POST") {
        if (inactive) {
          return inactive;
        }
        const stored = this.threadsConnections.get(account.id);
        if (!stored) {
          return json(
            409,
            errorBody(
              "threads_not_connected",
              "This Threads account is not connected.",
            ),
          );
        }
        if (stored.status === "reconnect_required") {
          return json(
            409,
            errorBody(
              "threads_reconnect_required",
              "The Threads connection needs to be renewed. Reconnect the account.",
            ),
          );
        }
        stored.last_verified_at = LATER;
        return json(200, this.threadsConnectionView(account.id));
      }
      if (action === "/disconnect" && method === "POST") {
        this.threadsConnections.delete(account.id);
        return json(200, this.threadsConnectionView(account.id));
      }
    }
    if ((match = path.match(/^\/threads\/oauth\/attempts\/([\w-]+)\/(\w+)$/))) {
      const attempt = this.threadsAttempts.get(match[1]);
      const action = match[2];
      if (!attempt) {
        return action === "complete"
          ? json(
              410,
              errorBody(
                "threads_oauth_attempt_expired",
                "This authorization has expired. Start the connection again.",
              ),
            )
          : json(
              404,
              errorBody(
                "threads_oauth_attempt_not_found",
                "This authorization was not found.",
              ),
            );
      }
      const notConfirmable = json(
        409,
        errorBody(
          "threads_oauth_attempt_not_confirmable",
          "This authorization is no longer waiting for a confirmation.",
        ),
      );
      if (action === "complete" && method === "POST") {
        if (attempt.status === "expired") {
          return json(
            410,
            errorBody(
              "threads_oauth_attempt_expired",
              "This authorization has expired. Start the connection again.",
            ),
          );
        }
        const pasted = (body as { redirect_url?: string } | null)?.redirect_url;
        let valid = false;
        try {
          const actual = new URL(pasted ?? "");
          const expected = new URL(TH_REDIRECT_URI);
          valid =
            actual.protocol === expected.protocol &&
            actual.host === expected.host &&
            actual.pathname === expected.pathname &&
            actual.username === "" &&
            actual.searchParams.has("code");
        } catch {
          valid = false;
        }
        if (!valid) {
          return json(
            400,
            errorBody(
              "threads_oauth_redirect_url_invalid",
              "The pasted address is not the address Threads redirected to.",
            ),
          );
        }
        if (attempt.status !== "pending") {
          return json(
            400,
            errorBody(
              "threads_oauth_state_invalid",
              "The pasted address does not belong to this connection attempt.",
            ),
          );
        }
        const outcome = this.nextThreadsOutcome;
        if (outcome.status === "completed") {
          this.setThreadsConnection(attempt.account_id, outcome.identity);
          attempt.status = "completed";
          attempt.connection = this.threadsConnectionView(attempt.account_id);
        } else {
          attempt.status = "awaiting_confirmation";
          attempt.new_identity = outcome.identity;
        }
        return json(200, attempt);
      }
      if (action === "confirm" && method === "POST") {
        if (attempt.status !== "awaiting_confirmation") {
          return notConfirmable;
        }
        this.setThreadsConnection(attempt.account_id, attempt.new_identity!);
        attempt.status = "completed";
        attempt.connection = this.threadsConnectionView(attempt.account_id);
        return json(200, attempt);
      }
      if (action === "cancel" && method === "POST") {
        if (
          !["pending", "awaiting_confirmation", "cancelled"].includes(
            attempt.status,
          )
        ) {
          return notConfirmable;
        }
        attempt.status = "cancelled";
        return json(200, attempt);
      }
    }
    return null;
  }

  /** Simplified Instagram connection rules: see 008 contracts/api.md. */
  private handleInstagram(
    path: string,
    method: string,
    body: unknown,
  ): Response | null {
    let match: RegExpMatchArray | null;
    if (
      (match = path.match(/^\/accounts\/(\d+)\/instagram-connection(\/\w+)?$/))
    ) {
      const account = this.accounts.find((a) => a.id === Number(match![1]));
      if (!account) {
        return json(404, errorBody("not_found", "Account not found."));
      }
      if (account.platform !== "instagram") {
        return json(
          409,
          errorBody(
            "platform_not_supported",
            "Only Instagram accounts can be connected.",
          ),
        );
      }
      const action = match[2];
      if (!action && method === "GET") {
        return json(200, this.instagramConnectionView(account.id));
      }
      const project = this.projects.find((p) => p.id === account.project_id)!;
      const inactive = !project.is_active
        ? json(
            409,
            errorBody(
              "project_inactive",
              "Reactivate the project before connecting accounts.",
            ),
          )
        : !account.is_active
          ? json(
              409,
              errorBody(
                "account_inactive",
                "Reactivate the account before connecting it.",
              ),
            )
          : null;
      if (action === "/authorize" && method === "POST") {
        if (inactive) {
          return inactive;
        }
        if (!this.instagramConfigured) {
          return json(
            503,
            errorBody(
              "instagram_oauth_not_configured",
              "Instagram integration is not configured. See docs/instagram-accounts.md.",
            ),
          );
        }
        for (const previous of this.instagramAttempts.values()) {
          if (
            previous.account_id === account.id &&
            previous.status === "pending"
          ) {
            previous.status = "expired";
          }
        }
        const attempt: InstagramOAuthAttempt = {
          attempt_id: `ig-attempt-${this.nextId++}`,
          account_id: account.id,
          status: "pending",
          expires_at: LATER,
          error: null,
          current_identity:
            this.instagramConnections.get(account.id)?.identity ?? null,
          new_identity: null,
          connection: null,
        };
        this.instagramAttempts.set(attempt.attempt_id, attempt);
        return json(201, {
          attempt_id: attempt.attempt_id,
          authorization_url: `https://www.instagram.com/oauth/authorize?state=${attempt.attempt_id}`,
          expires_at: attempt.expires_at,
        });
      }
      if (action === "/verify" && method === "POST") {
        if (inactive) {
          return inactive;
        }
        const stored = this.instagramConnections.get(account.id);
        if (!stored) {
          return json(
            409,
            errorBody(
              "instagram_not_connected",
              "This Instagram account is not connected.",
            ),
          );
        }
        if (stored.status === "reconnect_required") {
          return json(
            409,
            errorBody(
              "instagram_reconnect_required",
              "The Instagram connection needs to be renewed. Reconnect the account.",
            ),
          );
        }
        stored.last_verified_at = LATER;
        return json(200, this.instagramConnectionView(account.id));
      }
      if (action === "/disconnect" && method === "POST") {
        this.instagramConnections.delete(account.id);
        return json(200, this.instagramConnectionView(account.id));
      }
    }
    if (
      (match = path.match(/^\/instagram\/oauth\/attempts\/([\w-]+)\/(\w+)$/))
    ) {
      const attempt = this.instagramAttempts.get(match[1]);
      const action = match[2];
      if (!attempt) {
        return action === "complete"
          ? json(
              410,
              errorBody(
                "instagram_oauth_attempt_expired",
                "This authorization has expired. Start the connection again.",
              ),
            )
          : json(
              404,
              errorBody(
                "instagram_oauth_attempt_not_found",
                "This authorization was not found.",
              ),
            );
      }
      const notConfirmable = json(
        409,
        errorBody(
          "instagram_oauth_attempt_not_confirmable",
          "This authorization is no longer waiting for a confirmation.",
        ),
      );
      if (action === "complete" && method === "POST") {
        if (attempt.status === "expired") {
          return json(
            410,
            errorBody(
              "instagram_oauth_attempt_expired",
              "This authorization has expired. Start the connection again.",
            ),
          );
        }
        const pasted = (body as { redirect_url?: string } | null)?.redirect_url;
        if (!pasted?.startsWith(IG_REDIRECT_URI)) {
          return json(
            400,
            errorBody(
              "instagram_oauth_redirect_url_invalid",
              "The pasted address is not the address Instagram redirected to.",
            ),
          );
        }
        if (attempt.status !== "pending") {
          return json(
            400,
            errorBody(
              "instagram_oauth_state_invalid",
              "The pasted address does not belong to this connection attempt.",
            ),
          );
        }
        const outcome = this.nextInstagramOutcome;
        if (outcome.status === "completed") {
          this.setInstagramConnection(attempt.account_id, outcome.identity);
          attempt.status = "completed";
          attempt.connection = this.instagramConnectionView(attempt.account_id);
        } else {
          attempt.status = "awaiting_confirmation";
          attempt.new_identity = outcome.identity;
        }
        return json(200, attempt);
      }
      if (action === "confirm" && method === "POST") {
        if (attempt.status !== "awaiting_confirmation") {
          return notConfirmable;
        }
        this.setInstagramConnection(attempt.account_id, attempt.new_identity!);
        attempt.status = "completed";
        attempt.connection = this.instagramConnectionView(attempt.account_id);
        return json(200, attempt);
      }
      if (action === "cancel" && method === "POST") {
        if (
          !["pending", "awaiting_confirmation", "cancelled"].includes(
            attempt.status,
          )
        ) {
          return notConfirmable;
        }
        attempt.status = "cancelled";
        return json(200, attempt);
      }
    }
    return null;
  }

  /** Simplified YouTube connection rules: see 005 contracts/api.md. */
  private handleYouTube(path: string, method: string): Response | null {
    let match: RegExpMatchArray | null;
    if (
      (match = path.match(/^\/accounts\/(\d+)\/youtube-connection(\/\w+)?$/))
    ) {
      const account = this.accounts.find((a) => a.id === Number(match![1]));
      if (!account) {
        return json(404, errorBody("not_found", "Account not found."));
      }
      if (account.platform !== "youtube") {
        return json(
          409,
          errorBody(
            "platform_not_supported",
            "Only YouTube accounts can be connected.",
          ),
        );
      }
      const action = match[2];
      if (!action && method === "GET") {
        return json(200, this.connectionView(account.id));
      }
      if (action === "/authorize" && method === "POST") {
        const project = this.projects.find((p) => p.id === account.project_id)!;
        if (!project.is_active) {
          return json(
            409,
            errorBody(
              "project_inactive",
              "Reactivate the project before connecting accounts.",
            ),
          );
        }
        if (!account.is_active) {
          return json(
            409,
            errorBody(
              "account_inactive",
              "Reactivate the account before connecting it.",
            ),
          );
        }
        if (!this.oauthConfigured) {
          return json(
            503,
            errorBody(
              "oauth_not_configured",
              "YouTube integration is not configured. See the README section 'Connecting YouTube'.",
            ),
          );
        }
        const attempt: OAuthAttempt = {
          attempt_id: `attempt-${this.nextId++}`,
          account_id: account.id,
          status: "pending",
          expires_at: LATER,
          error: null,
          current_channel: this.connections.get(account.id)?.channel ?? null,
          new_channel: null,
          connection: null,
        };
        this.attempts.set(attempt.attempt_id, attempt);
        return json(201, {
          attempt_id: attempt.attempt_id,
          authorization_url: `https://accounts.google.com/o/oauth2/v2/auth?state=${attempt.attempt_id}`,
          expires_at: attempt.expires_at,
        });
      }
      if (action === "/verify" && method === "POST") {
        if (!this.connections.has(account.id)) {
          return json(
            409,
            errorBody(
              "not_connected",
              "This YouTube account is not connected.",
            ),
          );
        }
        const stored = this.connections.get(account.id)!;
        stored.status = "connected";
        stored.last_verified_at = LATER;
        return json(200, this.connectionView(account.id));
      }
      if (action === "/disconnect" && method === "POST") {
        this.connections.delete(account.id);
        return json(200, this.connectionView(account.id));
      }
    }
    if (
      (match = path.match(/^\/youtube\/oauth\/attempts\/([\w-]+)(\/\w+)?$/))
    ) {
      const attempt = this.attempts.get(match[1]);
      const notFound = json(
        404,
        errorBody(
          "oauth_attempt_not_found",
          "This authorization was not found.",
        ),
      );
      if (!attempt) {
        return notFound;
      }
      const action = match[2];
      if (!action && method === "GET") {
        if (attempt.status === "pending") {
          const outcome = this.nextAttemptOutcome;
          if (outcome.status === "not_found") {
            this.attempts.delete(attempt.attempt_id);
            return notFound;
          }
          if (outcome.status === "completed") {
            this.setConnection(attempt.account_id, outcome.channel);
            attempt.connection = this.connectionView(attempt.account_id);
          } else if (outcome.status === "awaiting_confirmation") {
            attempt.new_channel = outcome.channel;
          } else if (outcome.status === "failed") {
            attempt.error = { code: outcome.code, message: outcome.message };
          }
          attempt.status = outcome.status;
        }
        return json(200, attempt);
      }
      const notConfirmable = json(
        409,
        errorBody(
          "oauth_attempt_not_confirmable",
          "This authorization is no longer waiting for a confirmation.",
        ),
      );
      if (action === "/confirm" && method === "POST") {
        if (attempt.status !== "awaiting_confirmation") {
          return notConfirmable;
        }
        this.setConnection(attempt.account_id, attempt.new_channel!);
        attempt.status = "completed";
        attempt.connection = this.connectionView(attempt.account_id);
        return json(200, attempt);
      }
      if (action === "/cancel" && method === "POST") {
        if (
          !["pending", "awaiting_confirmation", "cancelled"].includes(
            attempt.status,
          )
        ) {
          return notConfirmable;
        }
        attempt.status = "cancelled";
        return json(200, attempt);
      }
    }
    return null;
  }

  /** Simplified preparation rules: see contracts/api.md. */
  private preparationError(
    projectId: number,
    content: Content | undefined,
    accounts: Account[],
  ): Response | null {
    const project = this.projects.find((p) => p.id === projectId)!;
    if (!project.is_active) {
      return json(
        409,
        errorBody(
          "project_inactive",
          "Reactivate the project before scheduling publications.",
        ),
      );
    }
    if (content && !content.file_available) {
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
        !HISTORY_STATUSES.includes(p.status) &&
        p.id !== excludeId,
    );
  }

  private sortedPublications(projectId: number): Publication[] {
    const rank = {
      publishing: 0,
      failed: 1,
      scheduled: 2,
      unscheduled: 3,
      published: 4,
      cancelled: 5,
    };
    return this.publications
      .filter((p) => p.project_id === projectId)
      .sort((a, b) => {
        if (a.status !== b.status) {
          return rank[a.status] - rank[b.status];
        }
        if (a.status === "scheduled" && a.scheduled_at !== b.scheduled_at) {
          return a.scheduled_at! < b.scheduled_at! ? -1 : 1;
        }
        if (a.status === "published" && a.published_at !== b.published_at) {
          return a.published_at! < b.published_at! ? 1 : -1;
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
    if (path === "/automation") {
      if (method === "PUT") {
        this.automation = {
          ...this.automation,
          paused: (body as { paused: boolean }).paused,
        };
      }
      return json(200, this.automation);
    }
    if ((match = path.match(/^\/projects\/(\d+)\/publications$/))) {
      const projectId = Number(match[1]);
      if (!this.projects.some((p) => p.id === projectId)) {
        return json(404, errorBody("not_found", "Project not found."));
      }
      return json(200, this.sortedPublications(projectId));
    }
    if (
      (match = path.match(/^\/projects\/(\d+)\/text-publications$/)) &&
      method === "POST"
    ) {
      const projectId = Number(match[1]);
      const values = body as {
        account_ids: number[];
        description: string | null;
        hashtags: string[];
        scheduled_at?: string;
        auto_publish_enabled?: boolean;
      };
      const ids = [...new Set(values.account_ids)];
      const accounts = ids.map((id) => this.accounts.find((a) => a.id === id)!);
      const error = this.preparationError(projectId, undefined, accounts);
      if (error) {
        return error;
      }
      const unsupported = accounts.filter(
        (account) => account.platform !== "threads",
      );
      if (unsupported.length > 0) {
        return json(
          422,
          errorBody(
            "text_publication_not_supported",
            "Some accounts cannot publish posts without media.",
            unsupported.map((account) => ({
              field: "account_ids",
              message: `${accountName(account)} cannot publish posts without media.`,
            })),
          ),
        );
      }
      const created = accounts.map((account) =>
        this.addPublication({
          content_id: null,
          account_id: account.id,
          description_override: values.description,
          hashtags_override: values.hashtags.map((tag) =>
            tag.replace(/^#/, ""),
          ),
          scheduled_at: values.scheduled_at ?? null,
          auto_publish_enabled: Boolean(values.auto_publish_enabled),
          created_at: LATER,
          updated_at: LATER,
        }),
      );
      return json(201, created);
    }
    if (
      (match = path.match(/^\/contents\/(\d+)\/publications$/)) &&
      method === "POST"
    ) {
      const content = this.contents.find((c) => c.id === Number(match![1]));
      if (!content) {
        return json(404, errorBody("not_found", "Content not found."));
      }
      const values = body as {
        account_ids: number[];
        scheduled_at?: string;
        auto_publish_enabled?: boolean;
      };
      if (values.auto_publish_enabled && !values.scheduled_at) {
        return json(
          422,
          errorBody("validation_error", "Invalid data.", [
            {
              field: "auto_publish_enabled",
              message: "Choose a date and time to enable auto-publish.",
            },
          ]),
        );
      }
      const ids = [...new Set(values.account_ids)];
      const accounts = ids.map((id) => this.accounts.find((a) => a.id === id)!);
      const error = this.preparationError(
        content.project_id,
        content,
        accounts,
      );
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
          auto_publish_enabled: Boolean(values.auto_publish_enabled),
          created_at: LATER,
          updated_at: LATER,
        }),
      );
      return json(201, created);
    }
    if ((match = path.match(/^\/publications\/(\d+)(\/[\w-]+)?$/))) {
      const record = this.publications.find((p) => p.id === Number(match![1]));
      if (!record) {
        return json(404, errorBody("not_found", "Publication not found."));
      }
      const action = match[2];
      const content = this.contents.find((c) => c.id === record.content_id);
      const account = this.accounts.find((a) => a.id === record.account_id)!;
      const notEditable = json(
        409,
        errorBody(
          "publication_not_editable",
          "This publication cannot be changed in its current state.",
        ),
      );
      if (action === "/youtube-options") {
        if (method === "PUT") {
          if (!this.optionsView(record).editable) {
            return notEditable;
          }
          this.youtubeOptions.set(record.id, body as StoredOptions);
        }
        return json(200, this.optionsView(record));
      }
      if (action === "/threads-options") {
        if (account.platform !== "threads") {
          return json(
            409,
            errorBody(
              "platform_not_supported",
              "Threads options only apply to publications of Threads accounts.",
            ),
          );
        }
        if (method === "PUT") {
          const view = this.threadsOptionsView(record);
          if (!view.editable) {
            return notEditable;
          }
          const altText =
            ((body as { alt_text: string | null }).alt_text ?? "").trim() ||
            null;
          if (altText !== null && view.media_kind === "text") {
            const message = "Alt text only applies to images and videos.";
            return json(
              422,
              errorBody("threads_option_not_applicable", message, [
                { field: "alt_text", message },
              ]),
            );
          }
          if (altText !== null && altText.length > 1000) {
            const message = "The alt text can have at most 1000 characters.";
            return json(
              422,
              errorBody("threads_alt_text_invalid", message, [
                { field: "alt_text", message },
              ]),
            );
          }
          this.threadsAltTexts.set(record.id, altText);
        }
        return json(200, this.threadsOptionsView(record));
      }
      if (action === "/instagram-options") {
        if (account.platform !== "instagram") {
          return json(
            409,
            errorBody(
              "platform_not_supported",
              "Instagram options only apply to publications of Instagram accounts.",
            ),
          );
        }
        if (method === "PUT") {
          if (!this.instagramOptionsView(record).editable) {
            return notEditable;
          }
          const values = body as Partial<StoredInstagramOptions>;
          const stored =
            this.instagramOptions.get(record.id) ?? DEFAULT_INSTAGRAM_OPTIONS;
          this.instagramOptions.set(record.id, {
            is_ai_generated: values.is_ai_generated ?? null,
            share_to_feed: values.share_to_feed ?? stored.share_to_feed,
            alt_text:
              values.alt_text === undefined
                ? stored.alt_text
                : (values.alt_text ?? "").trim() || null,
          });
        }
        return json(200, this.instagramOptionsView(record));
      }
      if (action === "/publish-check" && method === "GET") {
        return json(200, this.publishCheckView(record));
      }
      if (action === "/attempts" && method === "GET") {
        const attempts = this.publicationAttempts.get(record.id) ?? [];
        return json(200, [...attempts].reverse());
      }
      if (action === "/publish" && method === "POST") {
        const check = this.publishCheckView(record);
        const confirmed = (body as { confirm_remote_checked?: boolean } | null)
          ?.confirm_remote_checked;
        if (!check.eligible) {
          const problem = check.problems[0];
          return json(409, errorBody(problem.code, problem.message));
        }
        if (check.requires_remote_check && !confirmed) {
          return json(
            409,
            errorBody(
              "remote_check_required",
              "Check YouTube Studio before publishing again.",
            ),
          );
        }
        this.startAttempt(record);
        return json(202, this.publicationView(record));
      }
      if (
        ["publishing", "published"].includes(record.status) &&
        ((action === "/cancel" && method === "POST") ||
          (action === undefined && method === "PATCH"))
      ) {
        return notEditable;
      }
      if (action === "/cancel" && method === "POST") {
        if (record.status !== "cancelled") {
          Object.assign(record, {
            status: "cancelled",
            auto_publish_enabled: false,
            auto_publish_error: null,
            updated_at: LATER,
          });
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
        const error = this.preparationError(record.project_id, content, [
          account,
        ]);
        if (error) {
          return error;
        }
        if (
          record.content_id !== null &&
          this.activeFor(record.content_id, record.account_id, record.id)
        ) {
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
          auto_publish_enabled: false,
          auto_publish_error: null,
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
          const error = this.preparationError(record.project_id, content, [
            account,
          ]);
          if (error) {
            return error;
          }
        }
        if (patch.hashtags_override) {
          patch.hashtags_override = patch.hashtags_override.map((tag) =>
            tag.replace(/^#/, ""),
          );
        }
        const dateChanged =
          patch.scheduled_at !== undefined &&
          patch.scheduled_at !== record.scheduled_at;
        const resultDate =
          patch.scheduled_at !== undefined
            ? patch.scheduled_at
            : record.scheduled_at;
        if (patch.auto_publish_enabled && !resultDate) {
          return json(
            422,
            errorBody("validation_error", "Invalid data.", [
              {
                field: "auto_publish_enabled",
                message: "Choose a date and time to enable auto-publish.",
              },
            ]),
          );
        }
        Object.assign(record, patch, { updated_at: LATER });
        if (patch.scheduled_at !== undefined) {
          record.status = patch.scheduled_at ? "scheduled" : "unscheduled";
        }
        if (
          (dateChanged && patch.auto_publish_enabled === undefined) ||
          !record.scheduled_at
        ) {
          record.auto_publish_enabled = false;
        }
        if (dateChanged || patch.auto_publish_enabled !== undefined) {
          record.auto_publish_error = null;
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

    const tiktokResponse = this.handleTikTok(path, method);
    if (tiktokResponse) {
      return tiktokResponse;
    }
    const threadsResponse = this.handleThreads(path, method, body);
    if (threadsResponse) {
      return threadsResponse;
    }
    const instagramResponse = this.handleInstagram(path, method, body);
    if (instagramResponse) {
      return instagramResponse;
    }

    const youtubeResponse = this.handleYouTube(path, method);
    if (youtubeResponse) {
      return youtubeResponse;
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
