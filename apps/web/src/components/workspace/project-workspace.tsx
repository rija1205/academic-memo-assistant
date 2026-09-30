"use client";

import { ExportDialog } from "@/components/export/export-dialog";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useState, type CSSProperties, type FormEvent } from "react";
import { useAuth } from "@/components/auth/auth-provider";
import { SectionEditor, sectionStatusLabel } from "@/components/workspace/section-editor";
import { OutlineTree } from "@/components/workspace/outline-tree";
import {
  ApiError,
  archiveProject,
  createOutlineNode,
  deleteOutlineNode,
  deleteProject,
  duplicateOutlineNode,
  duplicateProject,
  getProject,
  getProjectOutline,
  getSection,
  listSectionRevisions,
  restoreSectionRevision,
  updateOutlineNode,
  updateProject,
  reorderProjectOutline,
  type OutlineNode,
  type Project,
  type EducationLevel,
  type ProjectStatus,
  type Section,
  type SectionRevision,
} from "@/lib/api";
import { moveOutlineNode } from "@/lib/workspace";

export function ProjectWorkspace({ projectId }: { projectId: string }) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { logout } = useAuth();
  const [project, setProject] = useState<Project | null>(null);
  const [outline, setOutline] = useState<OutlineNode[]>([]);
  const [selectedNode, setSelectedNode] = useState<OutlineNode | null>(null);
  const [section, setSection] = useState<Section | null>(null);
  const [revisions, setRevisions] = useState<SectionRevision[]>([]);
  const [compareLeftId, setCompareLeftId] = useState("");
  const [compareRightId, setCompareRightId] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [infoOpen, setInfoOpen] = useState(false);
  // Stage 11: the export is produced by the server from the same citation engine.
  const [exportOpen, setExportOpen] = useState(false);
  const [metadata, setMetadata] = useState({ title: "", domain: "", institution: "", education_level: "other" as EducationLevel, author_name: "", supervisor_name: "", academic_year: "", thesis_type: "", bibliography_style: "", problem_statement: "", general_objective: "", specific_objectives: "", hypotheses: "", keywords: "", status: "draft" as ProjectStatus });

  const loadOutline = useCallback(async () => {
    const nextOutline = await getProjectOutline(projectId);
    setOutline(nextOutline);
    setSelectedNode((current) => current ?? nextOutline[0] ?? null);
  }, [projectId]);

  const loadSection = useCallback(async (node: OutlineNode | null) => {
    if (!node) {
      setSection(null);
      setRevisions([]);
      return;
    }
    const nextSection = await getSection(projectId, node.section_id);
    setSection(nextSection);
    setRevisions(await listSectionRevisions(projectId, node.section_id));
  }, [projectId]);

  const refreshProject = useCallback(async () => {
    setProject(await getProject(projectId));
  }, [projectId]);

  const handleSectionSaved = useCallback(async (saved: Section) => {
    setSection(saved);
    try {
      setRevisions(await listSectionRevisions(projectId, saved.id));
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Historique indisponible.");
    }
    void refreshProject();
  }, [projectId, refreshProject]);

  const loadProject = useCallback(async () => {
    const nextProject = await getProject(projectId);
    setProject(nextProject);
    setMetadata({
      title: nextProject.title,
      domain: nextProject.domain ?? "",
      institution: nextProject.institution ?? "",
      education_level: nextProject.education_level,
      author_name: nextProject.author_name ?? "",
      supervisor_name: nextProject.supervisor_name ?? "",
      academic_year: nextProject.academic_year ?? "",
      thesis_type: nextProject.thesis_type,
      bibliography_style: nextProject.bibliography_style,
      problem_statement: nextProject.problem_statement ?? "",
      general_objective: nextProject.general_objective ?? "",
      specific_objectives: nextProject.specific_objectives.join("\n"),
      hypotheses: nextProject.hypotheses.join("\n"),
      keywords: nextProject.keywords.join(", "),
      status: nextProject.status,
    });
  }, [projectId]);

  useEffect(() => {
    Promise.all([loadProject(), loadOutline()])
      .catch((cause) => setError(cause instanceof ApiError ? cause.message : "Mémoire indisponible."))
      .finally(() => setLoading(false));
  }, [loadOutline, loadProject]);

  useEffect(() => {
    void loadSection(selectedNode).catch((cause) => setError(cause instanceof ApiError ? cause.message : "Section indisponible."));
  }, [loadSection, selectedNode]);

  useEffect(() => {
    setCompareLeftId((current) => revisions.some((revision) => revision.id === current) ? current : revisions[0]?.id ?? "");
    setCompareRightId((current) => revisions.some((revision) => revision.id === current) ? current : revisions[1]?.id ?? revisions[0]?.id ?? "");
  }, [revisions]);

  const comparedLeft = revisions.find((revision) => revision.id === compareLeftId);
  const comparedRight = revisions.find((revision) => revision.id === compareRightId);

  const selectedStatus = useMemo(() => section?.status ?? "empty", [section]);
  const canEdit = project !== null && project.access_role !== "reader";
  const canManage = project?.access_role === "owner";

  useEffect(() => {
    if (canEdit && searchParams.get("edit") === "1") setInfoOpen(true);
  }, [canEdit, searchParams]);

  async function refreshAfterMutation(nodeToLoad: OutlineNode | null = selectedNode) {
    await Promise.all([loadProject(), loadOutline()]);
    if (nodeToLoad) await loadSection(nodeToLoad);
  }

  async function addNode(parentId: string | null, kind: "section" | "subsection") {
    const title = window.prompt(kind === "section" ? "Titre de la nouvelle section" : "Titre de la sous-section");
    if (!title?.trim()) return;
    try {
      await createOutlineNode(projectId, { parent_id: parentId, kind, title: title.trim() });
      await refreshAfterMutation();
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Ajout impossible.");
    }
  }

  async function renameNode(node: OutlineNode) {
    const title = window.prompt("Nouveau titre", node.title);
    if (!title?.trim()) return;
    try {
      await updateOutlineNode(projectId, node.id, { title: title.trim() });
      await refreshAfterMutation();
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Renommage impossible.");
    }
  }

  async function removeNode(node: OutlineNode) {
    if (!window.confirm(`Supprimer « ${node.title} » et son contenu ?`)) return;
    try {
      await deleteOutlineNode(projectId, node.id);
      const nextSelected = selectedNode?.id === node.id ? null : selectedNode;
      if (nextSelected === null) setSelectedNode(null);
      await refreshAfterMutation(nextSelected);
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Suppression impossible.");
    }
  }

  async function copyNode(node: OutlineNode) {
    try {
      await duplicateOutlineNode(projectId, node.id);
      await refreshAfterMutation();
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Duplication impossible.");
    }
  }

  async function moveNode(node: OutlineNode, targetParentId: string | null, targetIndex: number) {
    try {
      const moves = moveOutlineNode(outline, node.id, targetParentId, targetIndex);
      await reorderProjectOutline(projectId, moves);
      await refreshAfterMutation();
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Déplacement impossible.");
    }
  }

  async function restoreRevision(revision: SectionRevision) {
    if (!section || !window.confirm(`Restaurer la version ${revision.version} ?`)) return;
    try {
      const restored = await restoreSectionRevision(projectId, section.id, revision.id);
      setSection(restored);
      setRevisions(await listSectionRevisions(projectId, section.id));
      await loadProject();
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Restauration impossible.");
    }
  }

  async function saveMetadata(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    try {
      const updated = await updateProject(projectId, {
        ...metadata,
        specific_objectives: metadata.specific_objectives
          .split("\n")
          .map((value) => value.trim())
          .filter(Boolean),
        hypotheses: metadata.hypotheses
          .split("\n")
          .map((value) => value.trim())
          .filter(Boolean),
        keywords: metadata.keywords
          .split(",")
          .map((value) => value.trim())
          .filter(Boolean),
      });
      setProject(updated);
      setInfoOpen(false);
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Enregistrement impossible.");
    }
  }

  async function handleArchive() {
    if (!project || !window.confirm("Archiver ce mémoire ?")) return;
    try {
      const archived = await archiveProject(project.id);
      setProject(archived);
      setMetadata((current) => ({ ...current, status: archived.status }));
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Archivage impossible.");
    }
  }

  async function handleDuplicateProject() {
    if (!project) return;
    try {
      const copy = await duplicateProject(project.id);
      window.location.assign(`/projects/${copy.id}`);
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Duplication impossible.");
    }
  }

  async function handleDeleteProject() {
    if (!project || !window.confirm(`Supprimer « ${project.title} » ? Cette action le retirera de votre espace.`)) return;
    try {
      await deleteProject(project.id);
      window.location.assign("/dashboard");
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Suppression impossible.");
    }
  }

  if (loading) return <div className="auth-loading">Chargement du mémoire…</div>;
  if (!project) return <div className="auth-loading">{error || "Mémoire introuvable."}</div>;

  return (
    <div className="project-workspace">
      <header className="workspace-project-header">
        <div><button className="back-link" type="button" onClick={() => router.push("/dashboard")}>← Mes mémoires</button><h1>{project.title}</h1><p>{project.domain || "Domaine non renseigné"} · {project.academic_year || "Année non renseignée"}</p></div>
        <div className="project-header-actions"><span className={`status-badge status-${project.status}`}>{project.status === "in_progress" ? "En cours" : project.status === "completed" ? "Terminé" : project.status === "archived" ? "Archivé" : "Brouillon"}</span><Link className="button button--secondary button--small" href="/profile">Profil</Link><button className="button button--secondary button--small" type="button" onClick={() => void logout()}>Déconnexion</button>{canEdit ? <button className="button button--secondary button--small" type="button" onClick={() => setInfoOpen((value) => !value)}>Modifier les informations</button> : null}{canManage ? <><button className="button button--secondary button--small" type="button" onClick={() => void handleDuplicateProject()}>Dupliquer</button><button className="button button--secondary button--small" type="button" onClick={() => void handleArchive()}>Archiver</button><button className="button button--danger button--small" type="button" onClick={() => void handleDeleteProject()}>Supprimer</button></> : null}</div>
      </header>
      {error ? <p className="form-error workspace-error" role="alert">{error}</p> : null}
      {infoOpen ? <form className="metadata-panel" onSubmit={saveMetadata}>
        <label className="auth-field"><span>Titre</span><input value={metadata.title} onChange={(event) => setMetadata((current) => ({ ...current, title: event.target.value }))} /></label>
        <label className="auth-field"><span>Domaine scientifique</span><input value={metadata.domain} onChange={(event) => setMetadata((current) => ({ ...current, domain: event.target.value }))} /></label>
        <label className="auth-field"><span>Établissement</span><input value={metadata.institution} onChange={(event) => setMetadata((current) => ({ ...current, institution: event.target.value }))} /></label>
        <label className="auth-field"><span>Niveau</span><select value={metadata.education_level} onChange={(event) => setMetadata((current) => ({ ...current, education_level: event.target.value as EducationLevel }))}><option value="licence">Licence</option><option value="master">Master</option><option value="doctorat">Doctorat</option><option value="other">Autre</option></select></label>
        <label className="auth-field"><span>Auteur</span><input value={metadata.author_name} onChange={(event) => setMetadata((current) => ({ ...current, author_name: event.target.value }))} /></label>
        <label className="auth-field"><span>Encadreur</span><input value={metadata.supervisor_name} onChange={(event) => setMetadata((current) => ({ ...current, supervisor_name: event.target.value }))} /></label>
        <label className="auth-field"><span>Année universitaire</span><input value={metadata.academic_year} onChange={(event) => setMetadata((current) => ({ ...current, academic_year: event.target.value }))} /></label>
        <label className="auth-field"><span>Type de mémoire</span><input value={metadata.thesis_type} onChange={(event) => setMetadata((current) => ({ ...current, thesis_type: event.target.value }))} /></label>
        <label className="auth-field"><span>Style bibliographique</span><input value={metadata.bibliography_style} onChange={(event) => setMetadata((current) => ({ ...current, bibliography_style: event.target.value }))} /></label>
        <label className="auth-field metadata-wide"><span>Problématique</span><textarea rows={3} value={metadata.problem_statement} onChange={(event) => setMetadata((current) => ({ ...current, problem_statement: event.target.value }))} /></label>
        <label className="auth-field metadata-wide"><span>Objectif général</span><textarea rows={3} value={metadata.general_objective} onChange={(event) => setMetadata((current) => ({ ...current, general_objective: event.target.value }))} /></label>
        <label className="auth-field metadata-wide"><span>Objectifs spécifiques (une ligne par objectif)</span><textarea rows={3} value={metadata.specific_objectives} onChange={(event) => setMetadata((current) => ({ ...current, specific_objectives: event.target.value }))} /></label>
        <label className="auth-field metadata-wide"><span>Hypothèses (une ligne par hypothèse)</span><textarea rows={3} value={metadata.hypotheses} onChange={(event) => setMetadata((current) => ({ ...current, hypotheses: event.target.value }))} /></label>
        <label className="auth-field metadata-wide"><span>Mots-clés (séparés par des virgules)</span><input value={metadata.keywords} onChange={(event) => setMetadata((current) => ({ ...current, keywords: event.target.value }))} /></label>
        <label className="auth-field"><span>Statut</span><select disabled={!canManage} value={metadata.status} onChange={(event) => setMetadata((current) => ({ ...current, status: event.target.value as ProjectStatus }))}><option value="draft">Brouillon</option><option value="in_progress">En cours</option><option value="completed">Terminé</option><option value="archived">Archivé</option></select></label>
        <div className="form-actions"><button className="button button--primary button--small" type="submit">Enregistrer</button><button className="button button--secondary button--small" type="button" onClick={() => setInfoOpen(false)}>Annuler</button></div>
      </form> : null}
      <div className="workspace-columns">
        <OutlineTree nodes={outline} selectedId={selectedNode?.id ?? null} canEdit={canEdit} onSelect={setSelectedNode} onAdd={(parentId, kind) => void addNode(parentId, kind)} onRename={(node) => void renameNode(node)} onDuplicate={(node) => void copyNode(node)} onDelete={(node) => void removeNode(node)} onMove={(node, parentId, index) => void moveNode(node, parentId, index)} />
        <main className="editor-column">
          {section ? <><div className="editor-section-heading"><div><p className="eyebrow">Section sélectionnée</p><h2>{section.title}</h2></div><span className={`section-status section-status--${selectedStatus}`}>{sectionStatusLabel(selectedStatus)}</span></div><SectionEditor key={section.id} section={section} readOnly={!canEdit} onSaved={handleSectionSaved} /></> : <div className="empty-panel">Sélectionnez une section dans la structure.</div>}
        {exportOpen ? <ExportDialog projectId={project.id} onClose={() => setExportOpen(false)} /> : null}
        </main>
        <aside className="info-column">
          <section className="info-panel"><div className="panel-heading"><h2>Informations</h2></div><div className="progress-ring" style={{ "--progress": `${project.progress * 3.6}deg` } as CSSProperties}><strong>{project.progress}%</strong><span>progression</span></div><div className="progress-legend"><span><i className="legend-dot complete" />{project.completed_sections} complétées</span><span><i className="legend-dot progress" />{project.in_progress_sections} en cours</span><span><i className="legend-dot empty" />{project.empty_sections} vides</span></div><dl className="info-list"><div><dt>TYPE</dt><dd>{project.thesis_type}</dd></div><div><dt> NIVEAU</dt><dd>{project.education_level}</dd></div><div><dt>AUTEUR</dt><dd>{project.author_name || "Non renseigné"}</dd></div><div><dt>ENCADREUR</dt><dd>{project.supervisor_name || "Non renseigné"}</dd></div></dl></section>
          <section className="info-panel"><div className="panel-heading"><h2>Sources & citations</h2></div><div className="module-placeholder"><span>＋</span><p>Les sources sont gérées dans la bibliothèque du projet.</p><small>{project.source_count} source · {project.reference_count} référence</small></div><Link className="button button--secondary button--full" href={`/projects/${project.id}/sources`}>Ouvrir mes sources</Link><Link className="button button--primary button--full" href={`/projects/${project.id}/rag`}>Rechercher dans mes sources</Link><Link className="button button--secondary button--full" href={`/projects/${project.id}/assistant`}>Ouvrir l&apos;assistant IA</Link><Link className="button button--secondary button--full" href={`/projects/${project.id}/bibliography`}>Gérer la bibliographie</Link><button className="button button--primary button--full" type="button" disabled={!canEdit} onClick={() => setExportOpen(true)}>Exporter le mémoire</button><Link className="button button--secondary button--full" href={`/projects/${project.id}/audit`}>Audit académique</Link></section>
          {section ? <section className="info-panel"><div className="panel-heading"><h2>Historique</h2><span>{revisions.length} versions</span></div><div className="revision-list">{revisions.map((revision) => <button type="button" className="revision-item" key={revision.id} onClick={() => void restoreRevision(revision)}><strong>Version {revision.version}</strong><span>{new Date(revision.created_at).toLocaleString("fr-FR")}</span><small>{revision.change_summary || "Sauvegarde"}</small></button>)}</div>{revisions.length > 1 ? <details className="revision-compare"><summary>Comparer deux versions</summary><div className="compare-selectors"><select aria-label="Version à comparer à gauche" value={compareLeftId} onChange={(event) => setCompareLeftId(event.target.value)}>{revisions.map((revision) => <option key={revision.id} value={revision.id}>Version {revision.version}</option>)}</select><select aria-label="Version à comparer à droite" value={compareRightId} onChange={(event) => setCompareRightId(event.target.value)}>{revisions.map((revision) => <option key={revision.id} value={revision.id}>Version {revision.version}</option>)}</select></div><div className="compare-columns"><article><strong>Version {comparedLeft?.version}</strong><pre>{comparedLeft?.plain_text || "(contenu vide)"}</pre></article><article><strong>Version {comparedRight?.version}</strong><pre>{comparedRight?.plain_text || "(contenu vide)"}</pre></article></div></details> : null}</section> : null}
          <section className="info-panel ai-panel"><div className="panel-heading"><h2>Assistant IA</h2><span className="module-status">Bientôt</span></div><button type="button" disabled>Demander à l&apos;IA</button><button type="button" disabled>Résumer</button><button type="button" disabled>Développer</button></section>
        </aside>
      </div>
    </div>
  );
}
