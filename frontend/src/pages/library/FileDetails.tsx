import { useState } from "react";
import { inspectContentMetadata, removeMetadata } from "../../api.ts";
import type {
  Content,
  FileMetadataReport,
  MetadataReport,
} from "../../types.ts";
import Button from "../../ui/Button.tsx";
import Disclosure from "../../ui/Disclosure.tsx";
import { formatBytes, formatDuration, toApiError } from "../../utils.ts";

/** What the metadata state means for the file Posts send (FR-013a). */
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
      <p className="ap-field__label">{label}</p>
      {!report.inspected ? (
        <p className="ap-meta">{report.reason ?? "Not inspected."}</p>
      ) : report.findings.length === 0 ? (
        <p className="ap-meta">No sensitive metadata found</p>
      ) : (
        <ul aria-label={`${label} metadata`}>
          {report.findings.map((finding) => (
            <li key={finding.category}>
              {finding.label}
              {finding.keys.length > 0 && (
                <span className="ap-meta"> ({finding.keys.join(", ")})</span>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

interface FileDetailsProps {
  content: Content;
  onChanged: () => Promise<void> | void;
}

/**
 * The file behind the Media, under a secondary disclosure: name, format,
 * dimensions, duration, size, the version Posts publish, metadata (inspect or
 * remove) and the checksums last.
 */
function FileDetails({ content, onChanged }: FileDetailsProps) {
  const [removing, setRemoving] = useState(false);
  const [inspecting, setInspecting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [report, setReport] = useState<MetadataReport | null>(null);
  const canRemove =
    content.metadata_status === "unknown" ||
    (content.metadata_status === "sanitized" &&
      !content.publish_file.available);
  const cleanCopy = content.publish_file.version === "clean_copy";

  async function handleRemove() {
    setRemoving(true);
    setError(null);
    try {
      await removeMetadata(content.id);
      setReport(null);
      await onChanged();
    } catch (caught) {
      setError(toApiError(caught).message);
    } finally {
      setRemoving(false);
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
    <Disclosure label="File details" className="ap-file-details">
      <div className="ap-file-details__body">
        <dl className="ap-media-facts">
          <dt>File name</dt>
          <dd>{content.original_filename}</dd>
          <dt>Format</dt>
          <dd>{content.media_format.toUpperCase()}</dd>
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
          <dt>Size</dt>
          <dd>{formatBytes(content.size_bytes)}</dd>
          <dt>Published version</dt>
          <dd>
            {cleanCopy
              ? `Clean copy without metadata (${formatBytes(content.publish_file.size_bytes)})`
              : "Original file"}
          </dd>
        </dl>
        <p>{metadataText(content)}</p>
        <div className="ap-file-details__actions">
          <Button loading={inspecting} onClick={() => void handleInspect()}>
            {inspecting ? "Inspecting…" : "Inspect metadata"}
          </Button>
          {canRemove && (
            <Button loading={removing} onClick={() => void handleRemove()}>
              {removing ? "Removing metadata…" : "Remove metadata"}
            </Button>
          )}
        </div>
        {error && (
          <p className="ap-field__error" role="alert">
            {error}
          </p>
        )}
        {report && (
          <div aria-label="Metadata found" role="group">
            <Findings label="Original" report={report.original} />
            {report.publish_copy && (
              <Findings label="Clean copy" report={report.publish_copy} />
            )}
          </div>
        )}
        <dl className="ap-media-facts ap-file-details__checksums">
          <dt>Checksum</dt>
          <dd className="ap-mono">{content.checksum}</dd>
          {cleanCopy && (
            <>
              <dt>Clean copy checksum</dt>
              <dd className="ap-mono">{content.publish_file.checksum}</dd>
            </>
          )}
        </dl>
      </div>
    </Disclosure>
  );
}

export default FileDetails;
