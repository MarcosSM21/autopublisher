import { ApiError } from "./api.ts";

export function toApiError(caught: unknown): ApiError {
  return caught instanceof ApiError
    ? caught
    : new ApiError(0, "unexpected_error", "Something went wrong.");
}

export function formatDate(value: string): string {
  return new Date(value).toLocaleString();
}
