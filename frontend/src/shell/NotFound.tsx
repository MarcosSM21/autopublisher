import { Link, useParams } from "react-router";

interface NotFoundProps {
  /** Where the single action leads; Home by default. */
  backTo?: { to: string; label: string };
}

/** A missing page, project, media or post: a message and one action. */
function NotFound({
  backTo = { to: "/", label: "Go to Home" },
}: NotFoundProps) {
  return (
    <section aria-labelledby="not-found-heading">
      <h1 id="not-found-heading">Not found</h1>
      <p>This page does not exist or is no longer available.</p>
      <p>
        <Link to={backTo.to}>{backTo.label}</Link>
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
