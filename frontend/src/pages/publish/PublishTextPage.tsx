import { useProject } from "../project-context.ts";
import PublishTask from "./PublishTask.tsx";

/**
 * /p/:projectId/posts/new[?posts=…]: a text post, with the same Publish task
 * as a Media (Compose → Review → Now/Schedule), only without Media.
 */
function PublishTextPage() {
  const { project } = useProject();
  return <PublishTask project={project} media={null} />;
}

export default PublishTextPage;
