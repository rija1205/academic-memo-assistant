"use client";

import { useParams } from "next/navigation";
import { AssistantWorkspace } from "@/components/assistant/assistant-workspace";
import { AuthGate } from "@/components/auth/auth-gate";
import { getProject, type Project } from "@/lib/api";
import { useEffect, useState } from "react";

function AssistantPageContent() {
  const params = useParams<{ projectId: string }>();
  const [project, setProject] = useState<Project | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    void getProject(params.projectId)
      .then(setProject)
      .catch(() => setError("Mémoire indisponible."));
  }, [params.projectId]);

  if (error) return <div className="auth-loading">{error}</div>;
  if (!project) return <div className="auth-loading">Chargement de l&apos;assistant…</div>;
  if (project.access_role === "reader") {
    return (
      <div className="auth-loading">
        L&apos;assistant académique n&apos;est pas disponible en lecture seule, car chaque question
        déclenche une génération facturée. Demandez le rôle éditeur au propriétaire du mémoire.
      </div>
    );
  }

  return (
    <div className="assistant-shell">
      <header className="assistant-topbar">
        <a href={`/projects/${project.id}`} className="back-link">← Retour au mémoire</a>
        <div>
          <strong>{project.title}</strong>
          <span>Assistant académique</span>
        </div>
        <nav className="assistant-topbar-links">
          <a className="button button--secondary button--small" href={`/projects/${project.id}/sources`}>
            Bibliothèque
          </a>
          <a className="button button--secondary button--small" href={`/projects/${project.id}/rag`}>
            Recherche RAG
          </a>
        </nav>
      </header>
      <AssistantWorkspace projectId={project.id} />
    </div>
  );
}

export default function ProjectAssistantPage() {
  return (
    <AuthGate>
      <AssistantPageContent />
    </AuthGate>
  );
}
