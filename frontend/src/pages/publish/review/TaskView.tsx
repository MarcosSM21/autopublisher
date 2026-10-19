import { useCallback, useEffect, useRef } from "react";
import { useAutosaveRegistry } from "../../../components/platform/autosave-registry.ts";
import type { Content, Project } from "../../../types.ts";
import { WHEN_DATE_ID } from "../final-action.ts";
import type { PublishTaskController } from "../usePublishTask.ts";
import ContentByDestination from "./ContentByDestination.tsx";
import ErrorSummary from "./ErrorSummary.tsx";
import FinalActions from "./FinalActions.tsx";
import PlatformDetailsList from "./PlatformDetailsList.tsx";
import ResultsSection from "./ResultsSection.tsx";
import ReviewDestinations from "./ReviewDestinations.tsx";
import WhenSection from "./WhenSection.tsx";

interface TaskViewProps {
  task: PublishTaskController;
  project: Project;
  media: Content | null;
  paused: boolean;
}

/**
 * The task once Drafts exist: Results first when some Posts already left
 * Draft, then Review ("Still to finish · N" in a mixed set) with the
 * destinations, the content each Draft really has, the platform details,
 * When and the single CTA. Must sit inside the task's AutosaveRegistry.
 */
function TaskView({ task, project, media, paused }: TaskViewProps) {
  const registry = useAutosaveRegistry();
  const { state, review, members, resultRows } = task;
  const reviewHeading = useRef<HTMLHeadingElement>(null);
  const mixed = resultRows.length > 0;

  // After Continue, the focus goes to the Review heading (once).
  const { dispatch } = task;
  const focusDone = useCallback(
    () => dispatch({ type: "focus_done" }),
    [dispatch],
  );
  useEffect(() => {
    if (state.focusReview) {
      reviewHeading.current?.focus();
      focusDone();
    }
  }, [state.focusReview, focusDone]);

  const submit = () => {
    if (registry) {
      void task.submit(registry);
    }
  };
  const dateError =
    task.summary.find((item) => item.target === WHEN_DATE_ID)?.text ?? null;
  const messages = Object.fromEntries(
    review.map((post) => {
      const step = state.steps[post.id];
      return [post.id, step?.status === "error" ? step.message : null];
    }),
  );

  return (
    <div className="ap-publish-task">
      {mixed && (
        <ResultsSection
          projectId={project.id}
          rows={resultRows}
          steps={state.steps}
          focus={state.focusResults}
          onFocused={focusDone}
        />
      )}
      {(review.length > 0 || members.length === 0) && (
        <section
          className="ap-publish-review"
          aria-labelledby="publish-review-title"
          aria-busy={task.validating || state.running !== null || undefined}
        >
          <h2
            id="publish-review-title"
            ref={reviewHeading}
            tabIndex={-1}
            className="ap-section-title"
          >
            {mixed ? `Still to finish · ${review.length}` : "Review"}
          </h2>
          {review.length > 0 && (
            <p className="ap-publish-review__saved">
              Your drafts are saved. You can finish them later.
            </p>
          )}
          <ReviewDestinations
            projectId={project.id}
            drafts={review}
            memberAccounts={members.map((post) => post.account_id)}
            destinations={task.destinations}
            onAdd={task.addDestination}
            onRemove={task.removeDestination}
            onAddToTask={task.addToTask}
          />
          {review.length > 0 && (
            <>
              <ContentByDestination
                drafts={review}
                onSave={task.updateContent}
                textPost={media === null}
              />
              <PlatformDetailsList
                drafts={review}
                declaration={task.declarationControl}
                messages={messages}
              />
              <WhenSection
                when={task.when}
                onWhenChange={task.setWhen}
                at={task.at}
                onAtChange={task.setAt}
                error={dateError}
                paused={paused}
              />
              <ErrorSummary
                items={task.summary}
                title="Fix these before anything starts"
              />
              <FinalActions
                projectId={project.id}
                count={review.length}
                when={task.when}
                busy={task.validating || state.running !== null}
                onSubmit={submit}
              />
            </>
          )}
          {review.length === 0 && (
            <p>
              No destinations in this task. Add one above
              {media
                ? `, or go back to ${media.title ?? media.original_filename}`
                : ""}
              .
            </p>
          )}
        </section>
      )}
    </div>
  );
}

export default TaskView;
