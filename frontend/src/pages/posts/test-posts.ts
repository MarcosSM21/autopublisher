// Test helpers for Posts: a minimal Publication with only what a test sets.
import type {
  PostDisplayState,
  Publication,
  PublicationAttempt,
} from "../../types.ts";

let nextId = 1000;

export function post(
  display_state: PostDisplayState,
  values: Partial<Publication> = {},
): Publication {
  const id = values.id ?? nextId++;
  return {
    id,
    project_id: 1,
    content_id: 10,
    account_id: 5,
    status: "unscheduled",
    scheduled_at: null,
    title_override: null,
    description_override: null,
    hashtags_override: null,
    title: null,
    description: "Caption",
    hashtags: [],
    content: null,
    account: {
      id: 5,
      platform: "youtube",
      handle: "chan",
      display_name: null,
      is_active: true,
    },
    project_active: true,
    published_at: null,
    latest_attempt: null,
    attempt_count: 0,
    auto_publish_enabled: false,
    auto_publish_state: null,
    auto_publish_window_ends_at: null,
    auto_publish_error: null,
    display_state,
    created_at: "2026-10-01T10:00:00Z",
    updated_at: "2026-10-01T10:00:00Z",
    ...values,
  };
}

export function attempt(
  values: Partial<PublicationAttempt> = {},
): PublicationAttempt {
  return {
    id: 1,
    publication_id: 1,
    platform: "youtube",
    trigger: "manual",
    status: "failed",
    stage: "done",
    started_at: "2026-10-01T10:00:00Z",
    finished_at: "2026-10-01T10:01:00Z",
    bytes_sent: 0,
    total_bytes: 0,
    progress: 0,
    error: null,
    outcome_determined: true,
    requires_manual_review: false,
    external_id: null,
    external_url: null,
    submitted: {},
    details: {},
    warnings: [],
    ...values,
  };
}
