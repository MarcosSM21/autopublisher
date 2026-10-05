import { useRef, useState, type DragEvent } from "react";
import { importFile } from "../api.ts";
import {
  ACCEPTED_FILE_TYPES,
  MAX_FILES_PER_IMPORT,
  type ImportItemResult,
  type Project,
} from "../types.ts";
import { toApiError } from "../utils.ts";

interface ContentImportProps {
  project: Project;
  onImported: () => void;
  onOpenContent?: (id: number) => void;
}

const STATUS_LABELS: Record<ImportItemResult["status"], string> = {
  imported: "Imported",
  duplicate: "Duplicate",
  rejected: "Rejected",
};

function ContentImport({
  project,
  onImported,
  onOpenContent,
}: ContentImportProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [progress, setProgress] = useState<{
    current: number;
    total: number;
  } | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [results, setResults] = useState<ImportItemResult[]>([]);
  // A ref guards against a second operation before the busy state re-renders.
  const busyRef = useRef(false);
  const busy = progress !== null;
  const disabled = !project.is_active || busy;

  // Files are sent one per request so that a failure only affects that file.
  async function importFiles(files: File[]) {
    if (!project.is_active || busyRef.current || files.length === 0) {
      return;
    }
    setResults([]);
    if (files.length > MAX_FILES_PER_IMPORT) {
      setMessage(
        `You can import at most ${MAX_FILES_PER_IMPORT} files at once.`,
      );
      return;
    }
    setMessage(null);
    busyRef.current = true;
    for (const [index, file] of files.entries()) {
      setProgress({ current: index + 1, total: files.length });
      try {
        const result = await importFile(project.id, file);
        setResults((previous) => [...previous, ...result.results]);
      } catch (caught) {
        const error = toApiError(caught);
        if (error.code === "project_inactive" || error.status === 404) {
          // The whole operation can no longer succeed.
          setMessage(error.message);
          break;
        }
        setResults((previous) => [
          ...previous,
          {
            filename: file.name,
            status: "rejected",
            content: null,
            existing_content: null,
            error: { code: error.code, message: error.message },
          },
        ]);
      }
    }
    busyRef.current = false;
    setProgress(null);
    onImported();
  }

  function handleDragOver(event: DragEvent<HTMLElement>) {
    event.preventDefault();
    if (!disabled) {
      setDragging(true);
    }
  }

  function handleDrop(event: DragEvent<HTMLElement>) {
    event.preventDefault();
    setDragging(false);
    void importFiles(Array.from(event.dataTransfer.files));
  }

  return (
    <div>
      <section
        aria-label="Import files"
        className={`dropzone${dragging ? " dragging" : ""}${
          disabled ? " disabled" : ""
        }`}
        onDragEnter={handleDragOver}
        onDragOver={handleDragOver}
        onDragLeave={() => setDragging(false)}
        onDrop={handleDrop}
      >
        {project.is_active ? (
          <p>Drop images or videos here, or</p>
        ) : (
          <p className="muted">Reactivate the project to import content.</p>
        )}
        <button
          type="button"
          disabled={disabled}
          onClick={() => inputRef.current?.click()}
        >
          Choose files
        </button>
        <input
          ref={inputRef}
          type="file"
          multiple
          hidden
          accept={ACCEPTED_FILE_TYPES}
          aria-label="Choose files"
          disabled={disabled}
          onChange={(event) => {
            const files = Array.from(event.target.files ?? []);
            event.target.value = "";
            void importFiles(files);
          }}
        />
      </section>
      {progress && (
        <p role="status">
          Importing {progress.current} of {progress.total}…
        </p>
      )}
      {message && (
        <p className="error" role="alert">
          {message}
        </p>
      )}
      {!busy && results.length > 0 && <Summary results={results} />}
      {results.length > 0 && (
        <ul className="plain import-results" aria-label="Import results">
          {results.map((result, index) => (
            <li key={index} className={`result-${result.status}`}>
              <span className="badge">{STATUS_LABELS[result.status]}</span>{" "}
              <span>{result.filename}</span>
              {result.error && (
                <span className="muted"> — {result.error.message}</span>
              )}
              {result.existing_content && (
                <>
                  <span className="muted">
                    {" "}
                    — Already in this project as “
                    {result.existing_content.title ??
                      result.existing_content.original_filename}
                    ”
                  </span>{" "}
                  {onOpenContent && (
                    <button
                      type="button"
                      className="link-button"
                      onClick={() => onOpenContent(result.existing_content!.id)}
                    >
                      Open
                    </button>
                  )}
                </>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function Summary({ results }: { results: ImportItemResult[] }) {
  const count = (status: ImportItemResult["status"]) =>
    results.filter((result) => result.status === status).length;
  const duplicates = count("duplicate");
  return (
    <p>
      {count("imported")} imported · {duplicates}{" "}
      {duplicates === 1 ? "duplicate" : "duplicates"} · {count("rejected")}{" "}
      rejected
    </p>
  );
}

export default ContentImport;
