import type { Content } from "../../types.ts";
import { isNotUsedYet } from "./usage-indicator.ts";

export type LibraryFilter = "all" | "images" | "videos" | "unused";

export const LIBRARY_FILTERS: ReadonlyArray<{
  value: LibraryFilter;
  label: string;
}> = [
  { value: "all", label: "All" },
  { value: "images", label: "Images" },
  { value: "videos", label: "Videos" },
  { value: "unused", label: "Not used yet" },
];

/** Search over title, file name, description and hashtags (case-insensitive). */
export function matchesSearch(content: Content, query: string): boolean {
  const needle = query.trim().toLowerCase().replace(/^#/, "");
  if (needle === "") {
    return true;
  }
  return [
    content.title ?? "",
    content.original_filename,
    content.description ?? "",
    ...content.hashtags,
  ].some((value) => value.toLowerCase().includes(needle));
}

export function matchesFilter(
  content: Content,
  filter: LibraryFilter,
): boolean {
  switch (filter) {
    case "images":
      return content.media_type === "image";
    case "videos":
      return content.media_type === "video";
    case "unused":
      return isNotUsedYet(content.usage);
    default:
      return true;
  }
}

/** The Media shown for a search and a filter: local state only, no URL. */
export function filterMedia(
  contents: Content[],
  query: string,
  filter: LibraryFilter,
): Content[] {
  return contents.filter(
    (content) =>
      matchesSearch(content, query) && matchesFilter(content, filter),
  );
}
