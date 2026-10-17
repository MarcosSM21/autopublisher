import { useState } from "react";
import { updateProject, type ProjectInput } from "../../api.ts";
import ProjectForm from "../../components/ProjectForm.tsx";
import type { Project } from "../../types.ts";
import Badge from "../../ui/Badge.tsx";
import Button from "../../ui/Button.tsx";
import { Dialog } from "../../ui/Dialog.tsx";
import Disclosure from "../../ui/Disclosure.tsx";
import { toApiError } from "../../utils.ts";

interface ProjectHeaderProps {
  project: Project;
  /** Reloads the project, its overview and the shell's project list. */
  onChanged: () => Promise<void>;
}

/** Compact header: name, "Inactive", and Edit / (De)activate behind a disclosure. */
function ProjectHeader({ project, onChanged }: ProjectHeaderProps) {
  const [editing, setEditing] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  async function handleSave(values: ProjectInput) {
    await updateProject(project.id, values);
    setEditing(false);
    await onChanged();
  }

  async function handleToggleActive() {
    setActionError(null);
    try {
      await updateProject(project.id, { is_active: !project.is_active });
      await onChanged();
    } catch (caught) {
      setActionError(toApiError(caught).message);
    }
  }

  return (
    <section className="ap-project-header" aria-label="Project">
      <div className="ap-project-header__main">
        <p className="ap-project-header__name">{project.name}</p>
        {!project.is_active && (
          <Badge tone="neutral" icon="pause">
            Inactive
          </Badge>
        )}
        <Disclosure
          label="Project actions"
          className="ap-project-header__actions"
        >
          <Button onClick={() => setEditing(true)}>Edit project</Button>
          <Button onClick={() => void handleToggleActive()}>
            {project.is_active ? "Deactivate project" : "Activate project"}
          </Button>
        </Disclosure>
      </div>
      {project.description && (
        <p className="ap-meta ap-project-header__description">
          {project.description}
        </p>
      )}
      {actionError && (
        <p className="error" role="alert">
          {actionError}
        </p>
      )}
      <Dialog open={editing} onOpenChange={setEditing} title="Edit project">
        <ProjectForm
          label="Edit project"
          initialValues={{
            name: project.name,
            description: project.description,
          }}
          submitLabel="Save"
          onSubmit={handleSave}
          onCancel={() => setEditing(false)}
        />
      </Dialog>
    </section>
  );
}

export default ProjectHeader;
