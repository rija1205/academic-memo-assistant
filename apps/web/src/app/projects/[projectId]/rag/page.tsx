"use client";

import { useParams } from "next/navigation";
import { AuthGate } from "@/components/auth/auth-gate";
import { RagWorkspace } from "@/components/rag/rag-workspace";
import { getProject, type Project } from "@/lib/api";
import { useEffect, useState } from "react";

function RagPageContent() {
  const params = useParams<{ projectId: string }>();
  const [project, setProject] = useState<Project | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    void getProject(params.projectId)
      .then(setProject)
      .catch(() => setError("Mémoire indisponible."));
  }, [params.projectId]);

  if (error) return <div className="auth-loading">{error}</div>;
  if (!project) return <div className="auth-loading">Chargement du moteur de recherche…</div>;

  return (
    <div className="rag-shell">
      <header className="rag-topbar">
        <a href={`/projects/${project.id}`} className="back-link">← Retour au mémoire</a>
        <div>
          <strong>{project.title}</strong>
          <span>Recherche dans mes sources</span>
        </div>
        <nav className="rag-topbar-links">
          <a className="button button--secondary button--small" href={`/projects/${project.id}/sources`}>
            Bibliothèque
          </a>
          <a className="button button--secondary button--small" href="/dashboard">Mes mémoires</a>
        </nav>
      </header>
      <RagWorkspace projectId={project.id} />
    </div>
  );
}

export default function ProjectRagPage() {
  return (
    <AuthGate>
      <RagPageContent />
    </AuthGate>
  );
}
