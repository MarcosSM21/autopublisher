import type { LibraryScope } from "../../api.ts";
import type { LibraryFolder } from "../../types.ts";

/** The URL of a Library view (contracts/ui.md §2). */
export function libraryViewPath(projectId: number, scope: LibraryScope) {
  const base = `/p/${projectId}/library`;
  switch (scope.kind) {
    case "all":
      return `${base}/all`;
    case "unsorted":
      return `${base}/unsorted`;
    default:
      return `${base}/folders/${scope.folderId}`;
  }
}

/** Where a Media lives: its folder's view, or Unsorted. */
export function locationScope(folderId: number | null): LibraryScope {
  return folderId === null
    ? { kind: "unsorted" }
    : { kind: "folder", folderId };
}

/** The folders directly under `parentId` (null = top level), in API order. */
export function childFolders(
  folders: readonly LibraryFolder[],
  parentId: number | null,
): LibraryFolder[] {
  return folders.filter((folder) => folder.parent_id === parentId);
}

/**
 * The tree in display order: each folder followed by its subfolders, siblings
 * in the API order (by name). Built from the flat list in one pass, so the
 * order only depends on the data.
 */
export function folderTreeOrder(
  folders: readonly LibraryFolder[],
): LibraryFolder[] {
  const byParent = new Map<number | null, LibraryFolder[]>();
  for (const folder of folders) {
    const siblings = byParent.get(folder.parent_id) ?? [];
    siblings.push(folder);
    byParent.set(folder.parent_id, siblings);
  }
  const ordered: LibraryFolder[] = [];
  const visit = (parentId: number | null) => {
    for (const folder of byParent.get(parentId) ?? []) {
      ordered.push(folder);
      visit(folder.id);
    }
  };
  visit(null);
  return ordered;
}

/** The folder and its ancestors, top level first; empty if it is unknown. */
export function folderPath(
  folders: readonly LibraryFolder[],
  folderId: number,
): LibraryFolder[] {
  const byId = new Map(folders.map((folder) => [folder.id, folder]));
  const path: LibraryFolder[] = [];
  let current = byId.get(folderId);
  // Depth bounds the walk, so a malformed list can never loop.
  while (current && path.length < folders.length) {
    path.unshift(current);
    current =
      current.parent_id === null ? undefined : byId.get(current.parent_id);
  }
  return path;
}

/** "Unsorted" or the folder's name. */
export function folderLabel(
  folders: readonly LibraryFolder[],
  folderId: number | null,
): string {
  if (folderId === null) {
    return "Unsorted";
  }
  return folders.find((folder) => folder.id === folderId)?.name ?? "Folder";
}
