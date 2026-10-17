import { useId, type ChangeEvent } from "react";
import { Link, useLocation, useNavigate } from "react-router";
import type { ProjectTarget } from "./useProjectTarget.ts";

interface ProjectSelectorProps {
  target: ProjectTarget;
  className?: string;
}

/**
 * Native select of the project (keyboard and screen-reader support for free).
 * Switching keeps the current section (library|posts|accounts) and drops the
 * detail id; from global context it opens the project's Library.
 */
function ProjectSelector({ target, className }: ProjectSelectorProps) {
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const selectId = useId();
  const { projects, projectId, section, loadFailed } = target;
  const classes = className
    ? `ap-project-selector ${className}`
    : "ap-project-selector";

  if (projects !== null && projects.length === 0) {
    return (
      <div className={classes}>
        <span className="ap-project-selector__label">Project</span>
        {loadFailed || pathname === "/" ? (
          // On Home the empty state already offers the one "Create project".
          <span className="ap-project-selector__note">
            {loadFailed ? "Projects unavailable" : "No projects yet"}
          </span>
        ) : (
          <Link className="ap-link" to="/">
            Create a project
          </Link>
        )}
      </div>
    );
  }

  const known = projects?.some((project) => project.id === projectId) ?? false;

  function handleChange(event: ChangeEvent<HTMLSelectElement>) {
    const id = parseInt(event.target.value, 10);
    if (Number.isInteger(id)) {
      void navigate(`/p/${id}/${section ?? "library"}`);
    }
  }

  return (
    <div className={classes}>
      <label className="ap-project-selector__label" htmlFor={selectId}>
        Project
      </label>
      <select
        id={selectId}
        className="ap-project-selector__select"
        value={known ? String(projectId) : ""}
        disabled={projects === null}
        onChange={handleChange}
      >
        {projects === null ? (
          <option value="">Loading…</option>
        ) : (
          <>
            {!known && (
              <option value="" disabled>
                Choose a project
              </option>
            )}
            {projects.map((project) => (
              <option key={project.id} value={project.id}>
                {project.is_active
                  ? project.name
                  : `${project.name} (inactive)`}
              </option>
            ))}
          </>
        )}
      </select>
    </div>
  );
}

export default ProjectSelector;
