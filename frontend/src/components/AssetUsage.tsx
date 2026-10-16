import { useEffect, useState } from "react";
import { getContentUsage } from "../api.ts";
import {
  PUBLICATION_STATUS_LABELS,
  platformLabel,
  type AssetPublication,
  type AssetUsage as AssetUsageData,
} from "../types.ts";
import { formatDate, toApiError } from "../utils.ts";

/** Awaiting the user in TikTok is a hand-off, never "Published". */
function statusLabel(publication: AssetPublication): string {
  if (
    publication.status === "awaiting_user_action" &&
    publication.platform === "tiktok"
  ) {
    return "Ready in TikTok";
  }
  return PUBLICATION_STATUS_LABELS[publication.status];
}

function AssetUsage({ contentId }: { contentId: number }) {
  const [data, setData] = useState<AssetUsageData | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let current = true;
    getContentUsage(contentId)
      .then((loaded) => current && setData(loaded))
      .catch((caught: unknown) => {
        if (current) setError(toApiError(caught).message);
      });
    return () => {
      current = false;
    };
  }, [contentId]);

  if (error) {
    return (
      <p className="error" role="alert">
        {error}
      </p>
    );
  }
  if (!data) return null;
  const { usage, publications } = data;
  const scheduled = publications.filter((p) => p.status === "scheduled");
  return (
    <section aria-label="Usage">
      <h4>Usage</h4>
      {publications.length === 0 ? (
        <p className="muted">Unused: no publications yet.</p>
      ) : (
        <>
          <p>
            {usage.published_count} published · {usage.awaiting_count} ready
            in TikTok · {usage.scheduled_count} scheduled ·{" "}
            {usage.publication_count} in total
          </p>
          <p className="muted">
            Last published:{" "}
            {usage.last_published_at
              ? formatDate(usage.last_published_at)
              : "never"}
          </p>
          {scheduled.length > 0 && (
            <p className="muted">
              Scheduled:{" "}
              {scheduled
                .map(
                  (p) =>
                    `${platformLabel(p.platform)} ${p.scheduled_at ? formatDate(p.scheduled_at) : ""}`,
                )
                .join(" · ")}
            </p>
          )}
          <ul className="plain" aria-label="Publications of this asset">
            {publications.map((publication) => (
              <li key={publication.publication_id}>
                <strong>{platformLabel(publication.platform)}</strong>{" "}
                {publication.account_name}{" "}
                <span className="badge">{statusLabel(publication)}</span>
                {publication.uncertain && (
                  <span className="badge">Uncertain</span>
                )}{" "}
                <span className="muted">
                  {publication.published_at
                    ? `Published ${formatDate(publication.published_at)}`
                    : `Updated ${formatDate(publication.updated_at)}`}
                </span>
                {publication.external_url && (
                  <>
                    {" "}
                    <a
                      href={publication.external_url}
                      target="_blank"
                      rel="noreferrer"
                    >
                      Open
                    </a>
                  </>
                )}
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}

export default AssetUsage;
