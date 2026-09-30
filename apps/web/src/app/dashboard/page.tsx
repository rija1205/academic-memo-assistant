"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { AppShell } from "@/components/app-shell";
import { AuthGate } from "@/components/auth/auth-gate";
import {
  ApiError,
  archiveProject,
  deleteProject,
  duplicateProject,
  listProjects,
  type ProjectSummary,
} from "@/lib/api";

function statusLabel(status: string): string {
  if (status === "in_progress") return "En cours";
  if (status === "completed") return "Terminé";
  if (status === "archived") return "Archivé";
  return "Brouillon";
}

function formatDate(value: string): string {
  return new Intl.DateTimeFormat("fr-FR", { dateStyle: "medium" }).format(new Date(value));
}

function levelLabel(level: string): string {
  if (level === "licence") return "Licence";
  if (level === "master") return "Master";
  if (level === "doctorat") return "Doctorat";
  return "Autre";
}

function DashboardContent() {
  const router = useRouter();
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  async function refresh() {
    setLoading(true);
    try {
      setProjects(await listProjects());
      setError("");
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Projets indisponibles.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { void refresh(); }, []);

  async function handleArchive(project: ProjectSummary) {
    try { await archiveProject(project.id); await refresh(); } catch (cause) { setError(cause instanceof ApiError ? cause.message : "Archivage impossible."); }
  }

  async function handleDuplicate(project: ProjectSummary) {
    try { const copy = await duplicateProject(project.id); router.push(`/projects/${copy.id}`); } catch (cause) { setError(cause instanceof ApiError ? cause.message : "Duplication impossible."); }
  }

  async function handleDelete(project: ProjectSummary) {
    if (!window.confirm(`Supprimer « ${project.title} » ?`)) return;
    try { await deleteProject(project.id); await refresh(); } catch (cause) { setError(cause instanceof ApiError ? cause.message : "Suppression impossible."); }
  }

  return (
    <AppShell>
      <div className="workspace-page-heading">
        <div><p className="eyebrow">Tableau de bord</p><h1>Mes mémoires</h1><p>Organisez votre recherche et votre rédaction dans un espace protégé.</p></div>
        <Link className="button button--primary" href="/projects/new">Nouveau mémoire</Link>
      </div>
      {error ? <p className="form-error" role="alert">{error}</p> : null}
      {loading ? <p className="empty-panel">Chargement de vos projets…</p> : null}
      {!loading && projects.length === 0 ? <section className="empty-panel"><span className="empty-icon" aria-hidden="true">＋</span><h2>Aucun projet pour le moment</h2><p>Créez votre premier mémoire pour commencer.</p><Link className="button button--primary" href="/projects/new">Créer un mémoire</Link></section> : null}
      {projects.length > 0 ? <section className="project-grid" aria-label="Liste des mémoires">{projects.map((project) => <article className="project-card" key={project.id}><div className="project-card-top"><span className="project-icon">▤</span><span className="role-badge">{project.access_role}</span></div><Link href={`/projects/${project.id}`} className="project-card-link"><h2>{project.title}</h2><p>{project.domain || "Domaine non renseigné"} · {levelLabel(project.education_level)}</p></Link><div className="project-card-meta"><span className={`status-badge status-${project.status}`}>{statusLabel(project.status)}</span><span>Modifié le {formatDate(project.updated_at)}</span><span>{project.progress}% · {project.section_count} sections · {project.source_count} sources · {project.reference_count} références</span></div><div className="progress-bar"><span style={{ width: `${project.progress}%` }} /></div><div className="project-card-actions"><Link href={`/projects/${project.id}`}>Ouvrir</Link>{project.access_role !== "reader" ? <Link href={`/projects/${project.id}?edit=1`}>Modifier</Link> : null}{project.access_role === "owner" ? <><button type="button" onClick={() => void handleDuplicate(project)}>Dupliquer</button><button type="button" onClick={() => void handleArchive(project)}>Archiver</button><button type="button" onClick={() => void handleDelete(project)}>Supprimer</button></> : null}</div></article>)}</section> : null}
      <section className="module-grid" aria-label="Modules à venir"><article className="module-card"><span className="module-icon">◈</span><h2>Mes sources</h2><p>Importez et organisez vos documents académiques.</p><Link className="button button--secondary button--small" href={projects[0] ? `/projects/${projects[0].id}/sources` : "/dashboard"}>Ouvrir la bibliothèque</Link></article><article className="module-card"><span className="module-icon">▥</span><h2>Bibliothèque</h2><p>Références et citations seront progressivement intégrées.</p><span className="module-status">Bientôt disponible</span></article><article className="module-card"><span className="module-icon">✦</span><h2>Assistant IA</h2><p>Les actions de rédaction et le RAG arrivent après l’éditeur.</p><span className="module-status">Bientôt disponible</span></article></section>
      <p className="workspace-note"><Link href="/profile">Gérer mon profil</Link> · <Link href="/settings">Ouvrir les paramètres</Link></p>
    </AppShell>
  );
}

export default function DashboardPage() {
  return <AuthGate><DashboardContent /></AuthGate>;
}
