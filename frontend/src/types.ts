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
