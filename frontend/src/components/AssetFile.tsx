import { useState } from "react";
import { inspectContentMetadata, removeMetadata } from "../api.ts";
import type { Content, FileMetadataReport, MetadataReport } from "../types.ts";
import { formatBytes, formatDuration, toApiError } from "../utils.ts";

/** What the metadata state means for the file publications send (FR-013a). */
function metadataText(content: Content): string {
  switch (content.metadata_status) {
    case "clean":
      return "Metadata checked: the original was already clean, so it is published as is.";
    case "sanitized":
      return content.publish_file.available
        ? "Metadata was removed: the clean copy is published instead of the original."
        : "Metadata was removed, but the clean copy is missing. Remove metadata again to recreate it; the original is never published instead.";
    default:
      return "Metadata not checked yet: the original is published as is.";
  }
}

function Findings({
  label,
  report,
}: {
  label: string;
  report: FileMetadataReport;
}) {
  return (
    <div>
      <strong>{label}</strong>
      {!report.inspected ? (
        <p className="muted">{report.reason ?? "Not inspected."}</p>
      ) : report.findings.length === 0 ? (
        <p className="muted">No sensitive metadata found</p>
      ) : (
        <ul aria-label={`${label} metadata`}>
          {report.findings.map((finding) => (
            <li key={finding.category}>
              {finding.label}
              {finding.keys.length > 0 && (
                <span className="muted"> ({finding.keys.join(", ")})</span>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

interface AssetFileProps {
  content: Content;
  onChanged: () => Promise<void>;
}

function AssetFile({ content, onChanged }: AssetFileProps) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [report, setReport] = useState<MetadataReport | null>(null);
  const [inspecting, setInspecting] = useState(false);
  const canRemove =
    content.metadata_status === "unknown" ||
    (content.metadata_status === "sanitized" &&
      !content.publish_file.available);
  const cleanCopy = content.publish_file.version === "clean_copy";

  async function handleRemove() {
    setBusy(true);
    setError(null);
    try {
      await removeMetadata(content.id);
      setReport(null);
      await onChanged();
    } catch (caught) {
      setError(toApiError(caught).message);
    } finally {
      setBusy(false);
    }
  }

  async function handleInspect() {
    setInspecting(true);
    setError(null);
    try {
      setReport(await inspectContentMetadata(content.id));
    } catch (caught) {
      setError(toApiError(caught).message);
    } finally {
      setInspecting(false);
    }
  }

  return (
    <section aria-label="File">
      <h4>File</h4>
      <dl>
        <dt>Original file</dt>
        <dd>{content.original_filename}</dd>
        <dt>Format</dt>
        <dd>{content.media_format.toUpperCase()}</dd>
        <dt>Size</dt>
        <dd>{formatBytes(content.size_bytes)}</dd>
        <dt>Dimensions</dt>
        <dd>
          {content.width !== null && content.height !== null
            ? `${content.width} × ${content.height}`
            : "—"}
        </dd>
        {content.media_type === "video" && (
          <>
            <dt>Duration</dt>
            <dd>{formatDuration(content.duration_seconds)}</dd>
          </>
        )}
        <dt>Checksum</dt>
        <dd className="muted">{content.checksum}</dd>
        <dt>Published version</dt>
        <dd>{cleanCopy ? "clean copy (without metadata)" : "original file"}</dd>
        {cleanCopy && (
          <>
            <dt>Clean copy size</dt>
            <dd>{formatBytes(content.publish_file.size_bytes)}</dd>
            <dt>Clean copy checksum</dt>
            <dd className="muted">{content.publish_file.checksum}</dd>
          </>
        )}
      </dl>
      <p>{metadataText(content)}</p>
      <div className="actions">
        <button type="button" onClick={handleInspect} disabled={inspecting}>
          {inspecting ? "Inspecting…" : "Inspect metadata"}
        </button>
        {canRemove && (
          <button type="button" onClick={handleRemove} disabled={busy}>
            {busy ? "Removing metadata…" : "Remove metadata"}
          </button>
        )}
      </div>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {report && (
        <div aria-label="Metadata found">
          <Findings label="Original" report={report.original} />
          {report.publish_copy && (
            <Findings label="Clean copy" report={report.publish_copy} />
          )}
        </div>
      )}
    </section>
  );
}

export default AssetFile;
