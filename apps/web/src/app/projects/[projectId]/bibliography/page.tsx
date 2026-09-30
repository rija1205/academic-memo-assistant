"use client";

import { BibliographyWorkspace } from "@/components/bibliography/bibliography-workspace";
import { AuthGate } from "@/components/auth/auth-gate";
import { getProject, type Project } from "@/lib/api";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

function BibliographyPageContent() {
  const params = useParams<{ projectId: string }>();
  const [project, setProject] = useState<Project | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    void getProject(params.projectId)
      .then(setProject)
      .catch(() => setError("M?moire indisponible."));
  }, [params.projectId]);

  if (error) return <div className="auth-loading">{error}</div>;
  if (!project) return <div className="auth-loading">Chargement de la bibliographie?</div>;

  return (
    <div className="bibliography-shell">
      <header className="bibliography-topbar">
        <a href={`/projects/${project.id}`} className="back-link">? Retour au m?moire</a>
        <div>
          <strong>{project.title}</strong>
          <span>Bibliographie</span>
        </div>
        <nav className="bibliography-topbar-links">
          <a className="button button--secondary button--small" href={`/projects/${project.id}/sources`}>
            Sources
          </a>
          <a className="button button--secondary button--small" href={`/projects/${project.id}/assistant`}>
            Assistant IA
          </a>
        </nav>
      </header>
      <BibliographyWorkspace
        projectId={project.id}
        canEdit={project.access_role !== "reader"}
        canDelete={project.access_role === "owner"}
      />
    </div>
  );
}

export default function ProjectBibliographyPage() {
  return (
    <AuthGate>
      <BibliographyPageContent />
    </AuthGate>
  );
}
