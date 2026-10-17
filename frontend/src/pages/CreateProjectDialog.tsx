import { useNavigate } from "react-router";
import { createProject, type ProjectInput } from "../api.ts";
import ProjectForm from "../components/ProjectForm.tsx";
import { Dialog } from "../ui/Dialog.tsx";

interface CreateProjectDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

/** Creates a project and opens its Library. */
function CreateProjectDialog({ open, onOpenChange }: CreateProjectDialogProps) {
  const navigate = useNavigate();

  async function handleCreate(values: ProjectInput) {
    const project = await createProject(values);
    onOpenChange(false);
    void navigate(`/p/${project.id}/library`);
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange} title="New project">
      <ProjectForm
        label="Create project"
        submitLabel="Create project"
        onSubmit={handleCreate}
        onCancel={() => onOpenChange(false)}
      />
    </Dialog>
  );
}

export default CreateProjectDialog;
