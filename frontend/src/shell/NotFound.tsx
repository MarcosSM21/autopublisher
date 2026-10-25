import { Link, useParams } from "react-router";
import Icon from "../ui/Icon.tsx";

interface NotFoundProps {
  /** Where the single action leads; Home by default. */
  backTo?: { to: string; label: string };
}

/** A missing page, project, media or post: a message and one action. */
function NotFound({
  backTo = { to: "/", label: "Go to Home" },
}: NotFoundProps) {
  return (
    <section className="ap-empty" aria-labelledby="not-found-heading">
      <span className="ap-empty__icon" aria-hidden="true">
        <Icon name="alert" />
      </span>
      <h1 id="not-found-heading" className="ap-empty__title">
        Not found
      </h1>
      <p className="ap-empty__text">
        This page does not exist or is no longer available.
      </p>
      <p className="ap-empty__actions">
        <Link className="ap-button ap-button--primary" to={backTo.to}>
          {backTo.label}
        </Link>
      </p>
    </section>
  );
}

/** An unknown section inside a project: back to that project's Library. */
export function ProjectNotFound() {
  const { projectId } = useParams();
  return (
    <NotFound
      backTo={{ to: `/p/${projectId}/library`, label: "Back to Library" }}
    />
  );
}

export default NotFound;
