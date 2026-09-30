"use client";

import { useParams } from "next/navigation";
import { AuthGate } from "@/components/auth/auth-gate";
import { SourcesWorkspace } from "@/components/sources/sources-workspace";
import { getProject, type Project } from "@/lib/api";
import { useEffect, useState } from "react";

function SourcesPageContent() {
  const params = useParams<{ projectId: string }>();
  const [project, setProject] = useState<Project | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    void getProject(params.projectId)
      .then(setProject)
      .catch(() => setError("Mémoire indisponible."));
  }, [params.projectId]);

  if (error) return <div className="auth-loading">{error}</div>;
  if (!project) return <div className="auth-loading">Chargement des sources…</div>;
  return (
    <div className="sources-shell">
      <header className="sources-topbar">
        <a href={`/projects/${project.id}`} className="back-link">← Retour au mémoire</a>
        <div><strong>{project.title}</strong><span>Sources académiques</span></div>
        <a className="button button--secondary button--small" href="/dashboard">Mes mémoires</a>
      </header>
      <SourcesWorkspace projectId={project.id} accessRole={project.access_role} />
    </div>
  );
}

export default function ProjectSourcesPage() {
  return <AuthGate><SourcesPageContent /></AuthGate>;
}
