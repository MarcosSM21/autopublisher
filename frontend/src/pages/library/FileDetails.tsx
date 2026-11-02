import { useState } from "react";
import { inspectContentMetadata } from "../../api.ts";
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
        : "Metadata was removed, but the clean copy is missing. Clean metadata again to recreate it; the original is never published instead.";
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
}

/** The file a report was read from: a clean or regenerated copy outdates it. */
function fileKey(content: Content): string {
  return `${content.metadata_status}:${content.publish_file.checksum}`;
}

/**
 * The file behind the Media, under a secondary disclosure: name, format,
 * dimensions, duration, size, the version Posts publish, metadata (inspect;
 * Clean metadata lives in the detail header) and the checksums last.
 */
function FileDetails({ content }: FileDetailsProps) {
  const [inspecting, setInspecting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [inspected, setInspected] = useState<{
    key: string;
    report: MetadataReport;
  } | null>(null);
  const report = inspected?.key === fileKey(content) ? inspected.report : null;
  const cleanCopy = content.publish_file.version === "clean_copy";

  async function handleInspect() {
    const key = fileKey(content);
    setInspecting(true);
    setError(null);
    try {
      setInspected({ key, report: await inspectContentMetadata(content.id) });
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
