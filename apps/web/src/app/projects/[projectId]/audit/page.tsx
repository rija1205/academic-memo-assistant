"use client";

import { AuthGate } from "@/components/auth/auth-gate";
import { AuditWorkspace } from "@/components/audit/audit-workspace";
import { getProject, type Project } from "@/lib/api";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

function AuditPageContent() {
  const params = useParams<{ projectId: string }>();
  const [project, setProject] = useState<Project | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    void getProject(params.projectId)
      .then(setProject)
      .catch(() => setError("Mémoire indisponible."));
  }, [params.projectId]);

  if (error) return <div className="auth-loading">{error}</div>;
  if (!project) return <div className="auth-loading">Chargement de l&apos;audit…</div>;

  return (
    <div className="audit-shell">
      <header className="audit-topbar">
        <a href={`/projects/${project.id}`} className="back-link">
          ← Retour au mémoire
        </a>
        <div>
          <strong>{project.title}</strong>
          <span>Audit académique</span>
        </div>
        <nav className="audit-topbar-links">
          <a
            className="button button--secondary button--small"
            href={`/projects/${project.id}/bibliography`}
          >
            Bibliographie
          </a>
        </nav>
      </header>
      <AuditWorkspace projectId={project.id} canRun={project.access_role !== "reader"} />
    </div>
  );
}

export default function ProjectAuditPage() {
  return (
    <AuthGate>
      <AuditPageContent />
    </AuthGate>
  );
}
