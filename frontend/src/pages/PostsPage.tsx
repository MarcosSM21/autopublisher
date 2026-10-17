import { useNavigate, useParams } from "react-router";
import { getPublication } from "../api.ts";
import PublicationQueue from "../components/PublicationQueue.tsx";
import { parseId } from "../route-params.ts";
import NotFound from "../shell/NotFound.tsx";
import { useProject } from "./project-context.ts";
import { useMissingFromProject } from "./useMissingFromProject.ts";

/** /p/:projectId/posts[/:postId]: the existing list (List view), selected by URL. */
function PostsPage() {
  const { project, reloadOverview } = useProject();
  const { postId } = useParams();
  const navigate = useNavigate();
  const selectedId = postId === undefined ? null : parseId(postId);
  const missing = useMissingFromProject(selectedId, project.id, getPublication);
  const base = `/p/${project.id}`;

  if ((postId !== undefined && selectedId === null) || missing) {
    return (
      <NotFound backTo={{ to: `${base}/posts`, label: "Back to Posts" }} />
    );
  }
  return (
    <>
      <h1>Posts</h1>

      <PublicationQueue
        project={project}
        onChanged={reloadOverview}
        selectedId={selectedId}
        onSelect={(id) =>
          void navigate(id === null ? `${base}/posts` : `${base}/posts/${id}`)
        }
      />
    </>
  );
}

export default PostsPage;
