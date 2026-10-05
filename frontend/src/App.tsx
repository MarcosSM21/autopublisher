import { useCallback, useEffect, useState } from "react";
import { createProject, listProjects, type ProjectInput } from "./api.ts";
import ProjectDetail from "./components/ProjectDetail.tsx";
import ProjectList from "./components/ProjectList.tsx";
import type { Project } from "./types.ts";
import { toApiError } from "./utils.ts";

function App() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<number | null>(null);

  // Data is always reloaded from the API after a change, so the UI never shows
  // something as saved before the backend has persisted it.
  const loadProjects = useCallback(
    () =>
      listProjects()
        .then((loadedProjects) => {
          setProjects(loadedProjects);
          setLoadError(null);
        })
        .catch((caught: unknown) => setLoadError(toApiError(caught).message))
        .finally(() => setLoaded(true)),
    [],
  );

  useEffect(() => {
    void loadProjects();
  }, [loadProjects]);

  async function handleCreate(values: ProjectInput) {
    const project = await createProject(values);
    setSelectedId(project.id);
    await loadProjects();
  }

  const selected = projects.find((project) => project.id === selectedId);

  return (
    <main>
      <h1>AutoPublisher</h1>
      {loadError && (
        <p className="error" role="alert">
          {loadError}
        </p>
      )}
      <div className="layout">
        <ProjectList
          projects={projects}
          loaded={loaded && !loadError}
          selectedId={selectedId}
          onSelect={setSelectedId}
          onCreate={handleCreate}
        />
        <div>
          {selected ? (
            <ProjectDetail
              key={selected.id}
              project={selected}
              onProjectChanged={loadProjects}
            />
          ) : (
            <p className="muted">Select a project to see its details.</p>
          )}
        </div>
      </div>
    </main>
  );
}

export default App;
