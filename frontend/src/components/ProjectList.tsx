import type { ProjectInput } from "../api.ts";
import type { Project } from "../types.ts";
import ProjectForm from "./ProjectForm.tsx";

interface ProjectListProps {
  projects: Project[];
  loaded: boolean;
  selectedId: number | null;
  onSelect: (id: number) => void;
  onCreate: (values: ProjectInput) => Promise<void>;
}

function ProjectList({
  projects,
  loaded,
  selectedId,
  onSelect,
  onCreate,
}: ProjectListProps) {
  return (
    <section aria-labelledby="projects-heading">
      <h2 id="projects-heading">Projects</h2>
      {loaded && projects.length === 0 && (
        <p className="muted">No projects yet. Create your first project.</p>
      )}
      <ul className="plain" aria-label="Projects">
        {projects.map((project) => (
          <li key={project.id}>
            <button
              type="button"
              className="project-button"
              aria-current={project.id === selectedId ? "true" : undefined}
              onClick={() => onSelect(project.id)}
            >
              <span className={project.is_active ? undefined : "inactive"}>
                {project.name}
              </span>
              {!project.is_active && <span className="badge">Inactive</span>}
            </button>
          </li>
        ))}
      </ul>
      <h3>New project</h3>
      <ProjectForm
        label="New project"
        submitLabel="Create project"
        onSubmit={onCreate}
        resetOnSuccess
      />
    </section>
  );
}

export default ProjectList;
