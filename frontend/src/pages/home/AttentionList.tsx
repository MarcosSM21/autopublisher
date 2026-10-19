import { useId } from "react";
import type { AttentionItem as Item, AttentionKind } from "../../types.ts";
import Button from "../../ui/Button.tsx";
import Icon from "../../ui/Icon.tsx";
import StatusBadge from "../../ui/StatusBadge.tsx";
import { formatWhen } from "../../utils.ts";
import { targetPath } from "./targets.ts";
import { problemText } from "../../components/platform/problem-copy.ts";

// Presentation only: how loud each kind looks. The order comes from the backend.
const URGENT: AttentionKind[] = ["manual_review", "failed", "missed"];

/** Items in the order the overview gives them; each has one action. */
function AttentionList({ items }: { items: Item[] }) {
  return (
    <section className="ap-home-section" aria-labelledby="home-attention-title">
      <h2 id="home-attention-title" className="ap-section-title">
        Needs attention <span className="ap-home-count">{items.length}</span>
      </h2>
      <ul className="ap-attention-list">
        {items.map((item) => (
          <AttentionItem
            key={`${item.kind}-${item.post?.id ?? `a${item.account.id}`}`}
            item={item}
          />
        ))}
      </ul>
    </section>
  );
}

function AttentionItem({ item }: { item: Item }) {
  const titleId = useId();
  const urgent = URGENT.includes(item.kind);
  const subject = item.post?.media_title ?? item.post?.excerpt ?? null;
  const context = [
    item.project.name,
    item.account.label,
    subject,
    // A post's time reads clearly; an account's date (e.g. an expiry) is
    // already explained by its detail, so it is not repeated unlabelled.
    item.post && item.at ? formatWhen(item.at) : null,
  ].filter(Boolean);

  return (
    <li
      className={urgent ? "ap-attention ap-attention--urgent" : "ap-attention"}
    >
      <Icon name="alert" className="ap-attention__icon" />
      <div className="ap-attention__body">
        <h3 id={titleId} className="ap-attention__title">
          {item.title}
        </h3>
        {item.detail && (
          <p className="ap-attention__detail">{problemText(item.detail)}</p>
        )}
        <p className="ap-meta ap-attention__context">{context.join(" · ")}</p>
        {item.affected_posts > 0 && (
          <p className="ap-meta">
            {item.affected_posts} scheduled{" "}
            {item.affected_posts === 1 ? "post" : "posts"} affected
          </p>
        )}
        {item.post && <StatusBadge post={item.post.display_state} />}
      </div>
      <Button
        as="link"
        to={targetPath(item.action.target)}
        variant="secondary"
        className="ap-attention__action"
        aria-describedby={titleId}
      >
        {item.action.label}
      </Button>
    </li>
  );
}

export default AttentionList;
