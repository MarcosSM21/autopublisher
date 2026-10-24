import { useState } from "react";
import { useNavigate } from "react-router";
import {
  deleteObject,
  getDeletionPreview,
  updateProject,
  type ProjectInput,
} from "../../api.ts";
import DeleteConfirmDialog from "../../components/DeleteConfirmDialog.tsx";
import ProjectForm from "../../components/ProjectForm.tsx";
import type { FlashState } from "../../shell/Flash.tsx";
import { useReloadProjects } from "../../shell/projects-reload.ts";
import type { Project } from "../../types.ts";
import Badge from "../../ui/Badge.tsx";
import Button from "../../ui/Button.tsx";
import { Dialog } from "../../ui/Dialog.tsx";
import Disclosure from "../../ui/Disclosure.tsx";
import { clearLastProjectId, getLastProjectId } from "../../ui-preferences.ts";
import { toApiError } from "../../utils.ts";

interface ProjectHeaderProps {
  project: Project;
  /** Reloads the project, its overview and the shell's project list. */
  onChanged: () => Promise<void>;
}

/**
 * Compact header: name, "Inactive", and Edit / (De)activate / Delete behind a
 * disclosure.
 */
function ProjectHeader({ project, onChanged }: ProjectHeaderProps) {
  const navigate = useNavigate();
  const reloadProjects = useReloadProjects();
  const [editing, setEditing] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const [deleting, setDeleting] = useState(false);
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

  /**
   * Gone (or already gone): Home, which shows the remaining projects or the
   * empty onboarding; nothing of this project is rendered or remembered.
   */
  function deleted() {
    setDeleting(false);
    if (getLastProjectId() === project.id) {
      clearLastProjectId();
    }
    const state: FlashState = { flash: "Project deleted." };
    void navigate("/", { replace: true, state });
    reloadProjects();
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
          open={menuOpen}
          onOpenChange={setMenuOpen}
        >
          <Button onClick={() => setEditing(true)}>Edit project</Button>
          <Button onClick={() => void handleToggleActive()}>
            {project.is_active ? "Deactivate project" : "Activate project"}
          </Button>
          <Button
            className="ap-delete-entry"
            onClick={() => {
              setMenuOpen(false);
              setDeleting(true);
            }}
          >
            Delete project
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
      {deleting && (
        <DeleteConfirmDialog
          title="Delete project?"
          loadPreview={() => getDeletionPreview("project", project.id)}
          remove={(confirmation) =>
            deleteObject("project", project.id, confirmation)
          }
          onDeleted={deleted}
          onClose={() => setDeleting(false)}
        />
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
