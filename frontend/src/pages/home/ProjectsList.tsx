import { Link } from "react-router";
import type { ProjectSummary } from "../../types.ts";
import Badge from "../../ui/Badge.tsx";
import Button from "../../ui/Button.tsx";
import { formatWhen } from "../../utils.ts";

interface ProjectsListProps {
  projects: ProjectSummary[];
  /** Absent when the list is filtered to one project. */
  onNewProject?: () => void;
}

/** Compact rows: name, problems or "All good", next post; open its Library. */
function ProjectsList({ projects, onNewProject }: ProjectsListProps) {
  return (
    <section
      className="ap-home-section ap-home-section--projects"
      aria-labelledby="home-projects-title"
    >
      <div className="ap-home-section__header">
        <h2 id="home-projects-title" className="ap-section-title">
          Projects
        </h2>
        {onNewProject && (
          <Button icon="plus" onClick={onNewProject}>
            New project
          </Button>
        )}
      </div>
      <ul className="ap-home-rows ap-home-tiles">
        {projects.map((project) => (
          <li key={project.id}>
            <Link
              className="ap-home-row ap-home-tile"
              to={`/p/${project.id}/library`}
            >
              <span className="ap-home-row__main">
                <span className="ap-home-row__title">{project.name}</span>
                <span className="ap-meta">
                  {project.next_post
                    ? `Next: ${formatWhen(project.next_post.scheduled_at)}`
                    : "Nothing scheduled"}
                </span>
              </span>
              <span className="ap-home-row__badges">
                {!project.is_active && (
                  <Badge tone="neutral" icon="pause">
                    Inactive
                  </Badge>
                )}
                {project.attention_count > 0 ? (
                  <Badge tone="warning" icon="alert">
                    {project.attention_count}{" "}
                    {project.attention_count === 1 ? "needs" : "need"} attention
                  </Badge>
                ) : (
                  <Badge tone="success" icon="check">
                    All good
                  </Badge>
                )}
              </span>
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}

export default ProjectsList;
