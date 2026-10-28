import { useRef, useState } from "react";
import { importFile } from "../../api.ts";
import {
  MAX_FILES_PER_IMPORT,
  type ImportItemResult,
  type Project,
} from "../../types.ts";
import { toApiError } from "../../utils.ts";

export interface ImportRun {
  total: number;
  /** 1-based index of the file being sent; 0 once finished. */
  current: number;
  results: ImportItemResult[];
  /** Why the whole import stopped or never started. */
  message: string | null;
}

export interface MediaImport {
  run: ImportRun | null;
  busy: boolean;
  disabled: boolean;
  importFiles: (files: File[]) => Promise<void>;
  dismiss: () => void;
}

/**
 * Importing files into the project: one request per file so a failure only
 * affects that file, progress while it runs, and the aggregate plus per-file
 * result once it finishes. The list is reloaded afterwards. Files go to
 * `folderId`, or to Unsorted when it is null. `onImported` gets the ids of the
 * Media this import created (never a duplicate's existing Media).
 */
export function useMediaImport(
  project: Project,
  folderId: number | null,
  onImported: (importedIds: number[]) => void,
): MediaImport {
  const [run, setRun] = useState<ImportRun | null>(null);
  // A ref guards against a second import before the busy state re-renders.
  const busyRef = useRef(false);
  const busy = run !== null && run.current > 0;
  const disabled = !project.is_active || busy;

  async function importFiles(files: File[]) {
    if (!project.is_active || busyRef.current || files.length === 0) {
      return;
    }
    if (files.length > MAX_FILES_PER_IMPORT) {
      setRun({
        total: files.length,
        current: 0,
        results: [],
        message: `You can import at most ${MAX_FILES_PER_IMPORT} files at once.`,
      });
      return;
    }
    busyRef.current = true;
    const importedIds: number[] = [];
    setRun({ total: files.length, current: 1, results: [], message: null });
    for (const [index, file] of files.entries()) {
      setRun((current) => current && { ...current, current: index + 1 });
      try {
        const result = await importFile(project.id, file, folderId);
        for (const item of result.results) {
          if (item.status === "imported" && item.content !== null) {
            importedIds.push(item.content.id);
          }
        }
        setRun(
          (current) =>
            current && {
              ...current,
              results: [...current.results, ...result.results],
            },
        );
      } catch (caught) {
        const error = toApiError(caught);
        if (error.code === "project_inactive" || error.status === 404) {
          // The whole import can no longer succeed (the project or the
          // folder is gone).
          setRun(
            (current) => current && { ...current, message: error.message },
          );
          break;
        }
        setRun(
          (current) =>
            current && {
              ...current,
              results: [
                ...current.results,
                {
                  filename: file.name,
                  status: "rejected",
                  content: null,
                  existing_content: null,
                  error: { code: error.code, message: error.message },
                },
              ],
            },
        );
      }
    }
    busyRef.current = false;
    setRun((current) => current && { ...current, current: 0 });
    onImported(importedIds);
  }

  return {
    run,
    busy,
    disabled,
    importFiles,
    dismiss: () => setRun(null),
  };
}
