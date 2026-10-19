import AutosaveRegistry from "../../components/platform/AutosaveRegistry.tsx";
import type { Content, Project } from "../../types.ts";
import Button from "../../ui/Button.tsx";
import ErrorState from "../../ui/ErrorState.tsx";
import Skeleton from "../../ui/Skeleton.tsx";
import { useProject } from "../project-context.ts";
import ComposeView from "./compose/ComposeView.tsx";
import MediaSummary from "./MediaSummary.tsx";
import TaskView from "./review/TaskView.tsx";
import { usePublishTask } from "./usePublishTask.ts";
import "./publish.css";

interface PublishTaskProps {
  project: Project;
  /** null: a text post (`/posts/new`), same task without Media. */
  media: Content | null;
}

/** Why nothing can be published from this page, or null. */
function blocker(project: Project, media: Content | null): string | null {
  if (!project.is_active) {
    return "Reactivate the project to publish.";
  }
  if (media !== null && !media.file_available) {
    return "The media file is missing, so it can't be published.";
  }
  return null;
}

/**
 * The Publish task of one Media (or of a text post), on one page: Compose (local) until
 * Continue, then Review, Results or both, rebuilt from `?posts=` alone.
 * A single column; on phones it is a task (no bottom navigation) with its
 * actions in a sticky bar.
 */
function PublishTask({ project, media }: PublishTaskProps) {
  const { overview } = useProject();
  const task = usePublishTask({ project, media });
  const { phase } = task.state;
  const reason = blocker(project, media);

  return (
    <div className="ap-publish">
      <div className="ap-publish__top">
        <Button
          as="link"
          to={
            media
              ? `/p/${project.id}/library/${media.id}`
              : `/p/${project.id}/posts`
          }
          variant="ghost"
          icon="back"
        >
          {media ? "Back to media" : "Back to Posts"}
        </Button>
      </div>
      <h1 className="ap-page-title">{media ? "Publish" : "Text post"}</h1>
      {media && <MediaSummary media={media} />}
      {reason && <p className="ap-notice">{reason}</p>}
      {task.state.notice && (
        <p className="ap-notice" role="status">
          {task.state.notice}
        </p>
      )}
      {task.loadError ? (
        <ErrorState
          title="Couldn't load this task"
          message={task.loadError}
          onRetry={task.retryLoad}
        />
      ) : phase === "loading" || task.context === null ? (
        <div aria-busy="true">
          <Skeleton lines={5} label="Loading destinations…" />
        </div>
      ) : phase === "task" ? (
        <AutosaveRegistry>
          <TaskView
            task={task}
            project={project}
            media={media}
            paused={overview?.automation.paused === true}
          />
        </AutosaveRegistry>
      ) : (
        <ComposeView
          task={task}
          project={project}
          media={media}
          presets={task.context.presets}
          onPresetsChange={task.setPresets}
        />
      )}
    </div>
  );
}

export default PublishTask;
