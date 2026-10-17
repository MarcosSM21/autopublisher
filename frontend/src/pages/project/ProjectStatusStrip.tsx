import { Link } from "react-router";
import type { Overview, ProjectSummary } from "../../types.ts";
import Icon from "../../ui/Icon.tsx";
import { formatWhen } from "../../utils.ts";

interface ProjectStatusStripProps {
  projectId: number;
  summary: ProjectSummary;
  automation: Overview["automation"];
}

/**
 * "Is this project ready, and what is coming next?" in one line of links; empty
 * items are left out. Attention is not listed here: it links to Home filtered.
 */
function ProjectStatusStrip({
  projectId,
  summary,
  automation,
}: ProjectStatusStripProps) {
  const base = `/p/${projectId}`;
  const items = [];

  if (summary.accounts_active > 0) {
    const allReady = summary.accounts_ready === summary.accounts_active;
    items.push(
      <Link key="accounts" className="ap-strip__item" to={`${base}/accounts`}>
        <Icon name={allReady ? "check" : "alert"} size={16} />
        {summary.accounts_ready}/{summary.accounts_active} accounts ready
      </Link>,
    );
  }
  if (summary.attention_count > 0) {
    items.push(
      <Link
        key="attention"
        className="ap-strip__item ap-strip__item--warning"
        to={`/?project=${projectId}`}
      >
        <Icon name="alert" size={16} />
        {summary.attention_count}{" "}
        {summary.attention_count === 1 ? "needs" : "need"} attention
      </Link>,
    );
  }
  if (summary.next_post) {
    items.push(
      <Link
        key="next"
        className="ap-strip__item"
        to={`${base}/posts/${summary.next_post.post_id}`}
      >
        <Icon name="clock" size={16} />
        Next: {formatWhen(summary.next_post.scheduled_at)}
      </Link>,
    );
  }
  if (automation.paused) {
    items.push(
      <Link
        key="paused"
        className="ap-strip__item ap-strip__item--warning"
        to="/settings"
      >
        <Icon name="pause" size={16} />
        Automation paused
        {automation.paused_automatic_posts > 0 &&
          ` · ${automation.paused_automatic_posts} waiting`}
      </Link>,
    );
  }
  if (items.length === 0) {
    return null;
  }
  return (
    <nav className="ap-strip" aria-label="Project status">
      <ul className="ap-strip__list">
        {items.map((item) => (
          <li key={item.key}>{item}</li>
        ))}
      </ul>
    </nav>
  );
}

export default ProjectStatusStrip;
