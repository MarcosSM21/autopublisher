import { useNavigate, useParams } from "react-router";
import { getContent } from "../api.ts";
import ContentLibrary from "../components/ContentLibrary.tsx";
import { parseId } from "../route-params.ts";
import NotFound from "../shell/NotFound.tsx";
import { useProject } from "./project-context.ts";
import { useMissingFromProject } from "./useMissingFromProject.ts";

/** /p/:projectId/library[/:mediaId]: the existing library, selected by URL. */
function LibraryPage() {
  const { project, overview, reloadOverview } = useProject();
  // Until an account is ready, "Connect an account" (onboarding) leads.
  const accountReady = overview?.projects[0]?.onboarding.account_ready === true;
  const { mediaId } = useParams();
  const navigate = useNavigate();
  const selectedId = mediaId === undefined ? null : parseId(mediaId);
  const missing = useMissingFromProject(selectedId, project.id, getContent);
  const base = `/p/${project.id}`;

  if ((mediaId !== undefined && selectedId === null) || missing) {
    return (
      <NotFound backTo={{ to: `${base}/library`, label: "Back to Library" }} />
    );
  }
  return (
    <>
      <h1>Library</h1>
      <ContentLibrary
        project={project}
        onChanged={reloadOverview}
        importIsPrimary={accountReady}
        selectedId={selectedId}
        onSelect={(id) =>
          void navigate(
            id === null ? `${base}/library` : `${base}/library/${id}`,
          )
        }
        onOpenPosts={(postId) =>
          void navigate(
            postId === undefined ? `${base}/posts` : `${base}/posts/${postId}`,
          )
        }
      />
    </>
  );
}

export default LibraryPage;
