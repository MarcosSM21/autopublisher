import type { RefObject } from "react";
import { Link } from "react-router";
import { ACCEPTED_FILE_TYPES, type ImportItemResult } from "../../types.ts";
import Badge, { type Tone } from "../../ui/Badge.tsx";
import IconButton from "../../ui/IconButton.tsx";
import type { MediaImport } from "./useMediaImport.ts";

const STATUS: Record<
  ImportItemResult["status"],
  { label: string; tone: Tone }
> = {
  imported: { label: "Imported", tone: "success" },
  duplicate: { label: "Duplicate", tone: "warning" },
  rejected: { label: "Rejected", tone: "danger" },
};

function summary(results: ImportItemResult[]): string {
  const count = (status: ImportItemResult["status"]) =>
    results.filter((result) => result.status === status).length;
  const duplicates = count("duplicate");
  return (
    `${count("imported")} imported · ${duplicates} ` +
    `${duplicates === 1 ? "duplicate" : "duplicates"} · ${count("rejected")} rejected`
  );
}

interface ImportPanelProps {
  importer: MediaImport;
  /** The hidden file input, opened directly by "Import media". */
  inputRef: RefObject<HTMLInputElement | null>;
  /** Link to a Media already in the project (duplicates). */
  mediaPath: (id: number) => string;
}

/**
 * The hidden file input and, while or after importing, an inline panel with
 * the progress, the aggregate result and the result of each file. It can be
 * dismissed once the import finished.
 */
function ImportPanel({ importer, inputRef, mediaPath }: ImportPanelProps) {
  const { run } = importer;
  return (
    <>
      <input
        ref={inputRef}
        type="file"
        multiple
        hidden
        accept={ACCEPTED_FILE_TYPES}
        aria-label="Choose files to import"
        disabled={importer.disabled}
        onChange={(event) => {
          const files = Array.from(event.target.files ?? []);
          event.target.value = "";
          void importer.importFiles(files);
        }}
      />
      {run && (
        <section
          className="ap-import-panel"
          aria-label="Import"
          aria-busy={importer.busy || undefined}
        >
          <div className="ap-import-panel__header">
            <p role="status" className="ap-import-panel__status">
              {importer.busy
                ? `Importing ${run.current} of ${run.total}…`
                : run.results.length > 0
                  ? summary(run.results)
                  : ""}
            </p>
            {!importer.busy && (
              <IconButton
                icon="close"
                label="Dismiss import results"
                onClick={importer.dismiss}
              />
            )}
          </div>
          {importer.busy && (
            <progress
              className="ap-import-panel__progress"
              value={run.current - 1}
              max={run.total}
              aria-label="Import progress"
            />
          )}
          {run.message && (
            <p className="ap-field__error" role="alert">
              {run.message}
            </p>
          )}
          {run.results.length > 0 && (
            <ul
              className="ap-import-panel__results"
              aria-label="Import results"
            >
              {run.results.map((result, index) => (
                <li key={index}>
                  <Badge tone={STATUS[result.status].tone}>
                    {STATUS[result.status].label}
                  </Badge>
                  <span className="ap-import-panel__file">
                    {result.filename}
                  </span>
                  {result.error && (
                    <span className="ap-meta">{result.error.message}</span>
                  )}
                  {result.existing_content && (
                    <span className="ap-meta">
                      Already in this project as “
                      {result.existing_content.title ??
                        result.existing_content.original_filename}
                      ”.{" "}
                      <Link
                        className="ap-link"
                        to={mediaPath(result.existing_content.id)}
                      >
                        Open
                      </Link>
                    </span>
                  )}
                </li>
              ))}
            </ul>
          )}
        </section>
      )}
    </>
  );
}

export default ImportPanel;
