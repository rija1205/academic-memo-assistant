"use client";

import {
  ApiError,
  createSourceFolder,
  deleteSource,
  deleteSourceFolder,
  getSourcePreview,
  listSourceFolders,
  listSources,
  reprocessSource,
  searchSources,
  sourceDownloadUrl,
  updateSource,
  uploadSource,
  type PublicationType,
  type Source,
  type SourceFolder,
  type SourceMetadataInput,
  type SourcePreview,
  type SourceSearchResult,
  type SourceStatus,
} from "@/lib/api";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

interface UploadState {
  id: string;
  name: string;
  size: number;
  type: string;
  progress: number;
  status: "uploading" | "uploaded" | "processing" | "processed" | "failed";
  error?: string;
  controller: AbortController;
}

function formatBytes(value: number): string {
  if (value < 1024) return `${value} o`;
  if (value < 1024 ** 2) return `${(value / 1024).toFixed(1)} Ko`;
  if (value < 1024 ** 3) return `${(value / 1024 ** 2).toFixed(1)} Mo`;
  return `${(value / 1024 ** 3).toFixed(1)} Go`;
}

function statusLabel(status: SourceStatus): string {
  if (status === "processing") return "Traitement";
  if (status === "processed") return "Prête";
  if (status === "failed") return "Échec";
  return "En attente";
}

function publicationLabel(value: PublicationType): string {
  const labels: Record<PublicationType, string> = {
    article: "Article scientifique",
    book: "Livre",
    book_chapter: "Chapitre de livre",
    thesis: "Thèse",
    memo: "Mémoire",
    report: "Rapport",
    conference: "Conférence",
    website: "Site web",
    other: "Autre",
  };
  return labels[value];
}

function createUploadItem(): UploadState {
  const controller = new AbortController();
  return {
    id: crypto.randomUUID(),
    name: "fichier",
    size: 0,
    type: "",
    progress: 0,
    status: "uploading",
    controller,
  };
}

export function SourcesWorkspace({
  projectId,
  accessRole,
}: {
  projectId: string;
  accessRole: "owner" | "editor" | "reader";
}) {
  const canEdit = accessRole !== "reader";
  const canManage = accessRole === "owner";
  const [sources, setSources] = useState<Source[]>([]);
  const [total, setTotal] = useState(0);
  const [folders, setFolders] = useState<SourceFolder[]>([]);
  const [selected, setSelected] = useState<Source | null>(null);
  const [preview, setPreview] = useState<SourcePreview | null>(null);
  const [pageNumber, setPageNumber] = useState(1);
  const [pageQuery, setPageQuery] = useState("");
  const [zoom, setZoom] = useState(100);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [query, setQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState<SourceStatus | "">("");
  const [typeFilter, setTypeFilter] = useState<PublicationType | "">("");
  const [folderFilter, setFolderFilter] = useState("");
  const [yearFilter, setYearFilter] = useState("");
  const [tagFilter, setTagFilter] = useState("");
  const [sort, setSort] = useState("imported_at");
  const [order, setOrder] = useState<"asc" | "desc">("desc");
  const [searchTerm, setSearchTerm] = useState("");
  const [searchResults, setSearchResults] = useState<SourceSearchResult[]>([]);
  const [searching, setSearching] = useState(false);
  const [uploads, setUploads] = useState<UploadState[]>([]);
  const [dragging, setDragging] = useState(false);
  const [editing, setEditing] = useState(false);
  const [metadata, setMetadata] = useState<SourceMetadataInput>({});
  const fileInput = useRef<HTMLInputElement>(null);

  const loadLibrary = useCallback(async () => {
    setLoading(true);
    try {
      const [result, nextFolders] = await Promise.all([
        listSources(projectId, {
          q: query || undefined,
          status: statusFilter || undefined,
          publication_type: typeFilter || undefined,
          folder_id: folderFilter || undefined,
          year: yearFilter ? Number(yearFilter) : undefined,
          tag: tagFilter || undefined,
          sort,
          order,
        }),
        listSourceFolders(projectId),
      ]);
      setSources(result.items);
      setTotal(result.total);
      setFolders(nextFolders);
      setError("");
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Sources indisponibles.");
    } finally {
      setLoading(false);
    }
  }, [folderFilter, order, projectId, query, sort, statusFilter, tagFilter, typeFilter, yearFilter]);

  useEffect(() => { void loadLibrary(); }, [loadLibrary]);

  useEffect(() => {
    if (!sources.some((source) => source.status === "processing" || source.status === "uploaded")) return;
    const timer = window.setInterval(() => { void loadLibrary(); }, 5000);
    return () => window.clearInterval(timer);
  }, [loadLibrary, sources]);

  async function openSource(source: Source) {
    setSelected(source);
    setPreview(null);
    setPageNumber(1);
    setPageQuery("");
    setEditing(false);
    try {
      setPreview(await getSourcePreview(projectId, source.id));
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Aperçu indisponible.");
    }
  }

  async function performUpload(file: File, allowDuplicate = false): Promise<void> {
    const item = createUploadItem();
    item.name = file.name;
    item.size = file.size;
    item.type = file.type || "type non détecté";
    setUploads((current) => [...current, item]);
    try {
      const uploaded = await uploadSource(projectId, file, {
        allowDuplicate,
        signal: item.controller.signal,
        onProgress: (progress) => {
          setUploads((current) => current.map((entry) => entry.id === item.id ? { ...entry, progress } : entry));
        },
      });
      setUploads((current) => current.map((entry) => entry.id === item.id ? { ...entry, progress: 100, status: uploaded.status } : entry));
      await loadLibrary();
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 409 && !allowDuplicate) {
        if (window.confirm("Ce document existe déjà dans le projet. L'ajouter quand même ?")) {
          await performUpload(file, true);
          return;
        }
        setUploads((current) => current.map((entry) => entry.id === item.id ? { ...entry, status: "failed", error: "Doublon confirmé, import annulé." } : entry));
        return;
      }
      const message = cause instanceof ApiError ? cause.message : "Import impossible.";
      setUploads((current) => current.map((entry) => entry.id === item.id ? { ...entry, status: "failed", error: message } : entry));
    }
  }

  async function handleFiles(files: FileList | File[]) {
    if (!canEdit) return;
    for (const file of Array.from(files)) await performUpload(file);
  }

  async function saveMetadata(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selected) return;
    try {
      const updated = await updateSource(projectId, selected.id, metadata);
      setSelected(updated);
      setEditing(false);
      await loadLibrary();
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Métadonnées non enregistrées.");
    }
  }

  async function runSearch() {
    if (searchTerm.trim().length < 2) {
      setSearchResults([]);
      return;
    }
    setSearching(true);
    try {
      const result = await searchSources(projectId, searchTerm.trim());
      setSearchResults(result.results);
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Recherche impossible.");
    } finally {
      setSearching(false);
    }
  }

  async function removeSource(source: Source) {
    if (!window.confirm(`Supprimer « ${source.title || source.original_filename} » ?`)) return;
    try {
      await deleteSource(projectId, source.id);
      if (selected?.id === source.id) setSelected(null);
      await loadLibrary();
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Suppression impossible.");
    }
  }

  async function retrySource(source: Source) {
    try {
      const updated = await reprocessSource(projectId, source.id);
      setSelected(updated);
      await loadLibrary();
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Relance impossible.");
    }
  }

  async function addFolder() {
    const name = window.prompt("Nom du dossier");
    if (!name?.trim()) return;
    try {
      await createSourceFolder(projectId, name.trim());
      await loadLibrary();
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Dossier impossible.");
    }
  }

  async function removeFolder(folder: SourceFolder) {
    if (!window.confirm(`Supprimer le dossier « ${folder.name} » ? Les sources seront conservées.`)) return;
    try {
      await deleteSourceFolder(projectId, folder.id);
      await loadLibrary();
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Suppression du dossier impossible.");
    }
  }

  const tagOptions = useMemo(
    () => Array.from(new Set(sources.flatMap((source) => source.tags))).sort(),
    [sources],
  );
  const currentPage = useMemo(
    () => preview?.pages.find((page) => page.page_number === pageNumber) ?? preview?.pages[0],
    [pageNumber, preview],
  );
  const visiblePageText = useMemo(() => {
    if (!currentPage) return "";
    if (!pageQuery.trim()) return currentPage.text;
    return currentPage.text.split(new RegExp(`(${pageQuery.trim().replace(/[.*+?^${}()|[\\]\\\\]/g, "\\$&")})`, "ig")).map((part, index) => part.toLowerCase() === pageQuery.trim().toLowerCase() ? <mark key={index}>{part}</mark> : part);
  }, [currentPage, pageQuery]);

  return (
    <div className="sources-page">
      <div className="sources-heading">
        <div><p className="eyebrow">Bibliothèque</p><h1>Mes sources</h1><p>Importez, vérifiez et organisez les documents de ce mémoire.</p></div>
        {canEdit ? <div className="sources-heading-actions"><button className="button button--secondary button--small" type="button" onClick={() => void addFolder()}>Nouveau dossier</button><button className="button button--primary" type="button" onClick={() => fileInput.current?.click()}>Ajouter une source</button></div> : null}
      </div>
      <input ref={fileInput} className="visually-hidden" type="file" multiple accept=".pdf,.docx,.txt,.md,.markdown,.csv,.xlsx,.png,.jpg,.jpeg" onChange={(event) => { if (event.target.files) void handleFiles(event.target.files); event.target.value = ""; }} />
      {canEdit ? <div className={`upload-dropzone ${dragging ? "dragging" : ""}`} onDragEnter={(event) => { event.preventDefault(); setDragging(true); }} onDragOver={(event) => event.preventDefault()} onDragLeave={() => setDragging(false)} onDrop={(event) => { event.preventDefault(); setDragging(false); if (event.dataTransfer.files) void handleFiles(event.dataTransfer.files); }}><strong>Déposez vos documents ici</strong><span>PDF, DOCX, TXT, Markdown, CSV, XLSX, PNG ou JPEG · {formatBytes(50 * 1024 * 1024)} max par fichier</span></div> : null}
      {uploads.length > 0 ? <div className="upload-queue">{uploads.map((upload) => <div className="upload-item" key={upload.id}><div className="upload-item-info"><strong>{upload.name}</strong><span>{formatBytes(upload.size)} · {upload.type}</span>{upload.error ? <small className="form-error">{upload.error}</small> : null}</div><div className="upload-progress"><div className="progress-bar"><span style={{ width: `${upload.progress}%` }} /></div><small>{upload.status === "uploading" ? `${upload.progress}%` : statusLabel(upload.status)}</small><button type="button" className="button button--danger button--small" onClick={() => upload.controller.abort()}>Annuler</button></div></div>)}</div> : null}
      {error ? <p className="form-error" role="alert">{error}</p> : null}
      <div className="sources-toolbar"><input aria-label="Rechercher dans la bibliothèque" placeholder="Rechercher un titre, auteur, DOI…" value={query} onChange={(event) => setQuery(event.target.value)} /><select aria-label="Filtrer par statut" value={statusFilter} onChange={(event) => setStatusFilter(event.target.value as SourceStatus | "")}><option value="">Tous les statuts</option><option value="uploaded">En attente</option><option value="processing">Traitement</option><option value="processed">Prêtes</option><option value="failed">Échecs</option></select><select aria-label="Filtrer par type" value={typeFilter} onChange={(event) => setTypeFilter(event.target.value as PublicationType | "")}><option value="">Tous les types</option>{Object.entries({ article: "Article", book: "Livre", book_chapter: "Chapitre", thesis: "Thèse", memo: "Mémoire", report: "Rapport", conference: "Conférence", website: "Site web", other: "Autre" } as Record<PublicationType, string>).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select><select aria-label="Filtrer par dossier" value={folderFilter} onChange={(event) => setFolderFilter(event.target.value)}><option value="">Tous les dossiers</option>{folders.map((folder) => <option key={folder.id} value={folder.id}>{folder.name}</option>)}</select><select aria-label="Filtrer par tag" value={tagFilter} onChange={(event) => setTagFilter(event.target.value)}><option value="">Tous les tags</option>{tagOptions.map((tag) => <option key={tag} value={tag}>{tag}</option>)}</select><input aria-label="Filtrer par année" type="number" placeholder="Année" value={yearFilter} onChange={(event) => setYearFilter(event.target.value)} /><select aria-label="Trier les sources" value={sort} onChange={(event) => setSort(event.target.value)}><option value="imported_at">Date d&apos;import</option><option value="updated_at">Dernière modification</option><option value="title">Titre</option><option value="publication_year">Année</option><option value="status">Statut</option></select><select aria-label="Ordre de tri" value={order} onChange={(event) => setOrder(event.target.value as "asc" | "desc")}><option value="desc">Décroissant</option><option value="asc">Croissant</option></select></div>
      {folders.length > 0 ? <div className="folder-chips"><span className="folder-chips-label">Dossiers :</span>{folders.map((folder) => <span className="folder-chip" key={folder.id}>{folder.name} ({folder.source_count}){canEdit ? <button type="button" onClick={() => void removeFolder(folder)} aria-label={`Supprimer le dossier ${folder.name}`}>×</button> : null}</span>)}</div> : null}
      <div className="sources-search"><input aria-label="Rechercher dans le texte extrait" placeholder="Rechercher dans le texte extrait…" value={searchTerm} onChange={(event) => setSearchTerm(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter") void runSearch(); }} /><button className="button button--secondary" type="button" onClick={() => void runSearch()} disabled={searching}>{searching ? "Recherche…" : "Rechercher"}</button>{searchResults.length > 0 ? <span>{searchResults.length} résultat(s)</span> : null}</div>
      {searchResults.length > 0 ? <div className="search-results">{searchResults.map((result) => <button type="button" className="search-result" key={result.provenance_id} onClick={() => { const found = sources.find((source) => source.id === result.source_id); if (found) void openSource(found); setPageNumber(result.page_number); }}><strong>{result.source_title}</strong><span>Page {result.page_number} · bloc {result.block_index}</span><small>{result.snippet}</small></button>)}</div> : null}
      <div className="sources-layout"><section className="source-list-panel"><div className="panel-heading"><h2>Documents</h2><span>{total} source(s)</span></div>{loading ? <p className="empty-panel">Chargement…</p> : sources.length === 0 ? <div className="empty-panel"><span className="empty-icon">＋</span><p>Aucune source importée.</p></div> : <div className="source-list">{sources.map((source) => <article className={`source-card ${selected?.id === source.id ? "selected" : ""}`} key={source.id}><button type="button" className="source-card-main" onClick={() => void openSource(source)}><div className="source-file-icon">{source.extension.replace(".", "").toUpperCase()}</div><div><strong>{source.title || source.original_filename}</strong><span>{source.authors.join(", ") || "Auteur non renseigné"} · {source.publication_year || "Année non renseignée"}</span><small>{publicationLabel(source.publication_type)} · {statusLabel(source.status)} · {source.page_count ? `${source.page_count} page(s)` : "Pages non renseignées"}</small></div></button><div className="source-card-footer"><span>{formatBytes(source.size_bytes)}</span><span>{new Date(source.imported_at).toLocaleDateString("fr-FR")}</span>{source.status === "failed" && canEdit ? <button type="button" onClick={() => void retrySource(source)}>Réessayer</button> : null}</div>{source.error_message ? <p className="form-error source-error">{source.error_message}</p> : null}</article>)}</div>}</section>
        <section className="source-detail-panel">{selected ? <><div className="source-detail-heading"><div><p className="eyebrow">Aperçu et métadonnées</p><h2>{selected.title || selected.original_filename}</h2><p>{selected.original_filename} · SHA-256 {selected.sha256.slice(0, 16)}…</p></div><div className="source-detail-actions">{canEdit ? <button className="button button--secondary button--small" type="button" onClick={() => { setEditing((value) => !value); setMetadata({ title: selected.title, authors: selected.authors, publication_year: selected.publication_year, doi: selected.doi, url: selected.url, journal: selected.journal, volume: selected.volume, issue: selected.issue, pages: selected.pages, publisher: selected.publisher, publication_type: selected.publication_type, abstract: selected.abstract, keywords: selected.keywords, folder_id: selected.folder_id, tags: selected.tags }); }}>Modifier</button> : null}{canEdit ? <a className="button button--secondary button--small" href={sourceDownloadUrl(projectId, selected.id)}>Télécharger</a> : null}{canManage ? <button className="button button--danger button--small" type="button" onClick={() => void removeSource(selected)}>Supprimer</button> : null}</div></div>{editing ? <form className="source-metadata-form" onSubmit={saveMetadata}><label className="auth-field"><span>Titre</span><input value={metadata.title ?? ""} onChange={(event) => setMetadata((current) => ({ ...current, title: event.target.value }))} /></label><label className="auth-field"><span>Auteurs (séparés par des virgules)</span><input value={metadata.authors?.join(", ") ?? ""} onChange={(event) => setMetadata((current) => ({ ...current, authors: event.target.value.split(",").map((value) => value.trim()).filter(Boolean) }))} /></label><label className="auth-field"><span>Année</span><input type="number" value={metadata.publication_year ?? ""} onChange={(event) => setMetadata((current) => ({ ...current, publication_year: event.target.value ? Number(event.target.value) : null }))} /></label><label className="auth-field"><span>DOI</span><input value={metadata.doi ?? ""} onChange={(event) => setMetadata((current) => ({ ...current, doi: event.target.value }))} /></label><label className="auth-field"><span>URL</span><input value={metadata.url ?? ""} onChange={(event) => setMetadata((current) => ({ ...current, url: event.target.value }))} /></label><label className="auth-field"><span>Journal / éditeur</span><input value={metadata.journal ?? ""} onChange={(event) => setMetadata((current) => ({ ...current, journal: event.target.value }))} /></label><label className="auth-field"><span>Volume</span><input value={metadata.volume ?? ""} onChange={(event) => setMetadata((current) => ({ ...current, volume: event.target.value }))} /></label><label className="auth-field"><span>Numéro</span><input value={metadata.issue ?? ""} onChange={(event) => setMetadata((current) => ({ ...current, issue: event.target.value }))} /></label><label className="auth-field"><span>Pages</span><input value={metadata.pages ?? ""} onChange={(event) => setMetadata((current) => ({ ...current, pages: event.target.value }))} /></label><label className="auth-field"><span>Éditeur</span><input value={metadata.publisher ?? ""} onChange={(event) => setMetadata((current) => ({ ...current, publisher: event.target.value }))} /></label><label className="auth-field"><span>Type</span><select value={metadata.publication_type ?? "other"} onChange={(event) => setMetadata((current) => ({ ...current, publication_type: event.target.value as PublicationType }))}>{Object.entries({ article: "Article scientifique", book: "Livre", book_chapter: "Chapitre de livre", thesis: "Thèse", memo: "Mémoire", report: "Rapport", conference: "Conférence", website: "Site web", other: "Autre" } as Record<PublicationType, string>).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label><label className="auth-field"><span>Dossier</span><select value={metadata.folder_id ?? ""} onChange={(event) => setMetadata((current) => ({ ...current, folder_id: event.target.value || null }))}><option value="">Sans dossier</option>{folders.map((folder) => <option key={folder.id} value={folder.id}>{folder.name}</option>)}</select></label><label className="auth-field source-form-wide"><span>Mots-clés (séparés par des virgules)</span><input value={metadata.keywords?.join(", ") ?? ""} onChange={(event) => setMetadata((current) => ({ ...current, keywords: event.target.value.split(",").map((value) => value.trim()).filter(Boolean) }))} /></label><label className="auth-field source-form-wide"><span>Tags (séparés par des virgules)</span><input value={metadata.tags?.join(", ") ?? ""} onChange={(event) => setMetadata((current) => ({ ...current, tags: event.target.value.split(",").map((value) => value.trim()).filter(Boolean) }))} /></label><label className="auth-field source-form-wide"><span>Résumé</span><textarea rows={4} value={metadata.abstract ?? ""} onChange={(event) => setMetadata((current) => ({ ...current, abstract: event.target.value }))} /></label><div className="form-actions"><button className="button button--primary button--small" type="submit">Enregistrer</button><button className="button button--secondary button--small" type="button" onClick={() => setEditing(false)}>Annuler</button></div></form> : null}
          {selected.status === "failed" ? <p className="form-error">Traitement échoué : {selected.error_message || "erreur inconnue"}. Vous pouvez relancer le traitement.</p> : null}
          {preview ? <div className="source-preview"><div className="preview-toolbar"><div><button className="button button--secondary button--small" type="button" onClick={() => setPageNumber((value) => Math.max(1, value - 1))}>←</button><span>Page {currentPage?.page_number ?? pageNumber} / {preview.pages.length}</span><button className="button button--secondary button--small" type="button" onClick={() => setPageNumber((value) => Math.min(preview.pages.length, value + 1))}>→</button></div><div><button className="button button--secondary button--small" type="button" onClick={() => setZoom((value) => Math.max(60, value - 10))}>−</button><span>{zoom}%</span><button className="button button--secondary button--small" type="button" onClick={() => setZoom((value) => Math.min(200, value + 10))}>+</button></div><input aria-label="Rechercher dans la page" placeholder="Rechercher dans la page…" value={pageQuery} onChange={(event) => setPageQuery(event.target.value)} /></div>{canEdit && selected.mime_type === "application/pdf" ? <div className="pdf-preview"><iframe title="Aperçu PDF" src={sourceDownloadUrl(projectId, selected.id, true)} style={{ width: `${zoom}%` }} /></div> : null}<article className="extracted-preview"><h3>Texte extrait · provenance conservée</h3><pre>{visiblePageText || "Aucun texte sur cette page."}</pre></article><small className="provenance-note">Chaque bloc conserve sa page, son index et un identifiant de provenance pour les futures citations.</small></div> : <div className="empty-panel"><span className="empty-icon">▤</span><p>Sélectionnez une source pour consulter son aperçu et son texte extrait.</p></div>}</> : <div className="empty-panel"><span className="empty-icon">▤</span><h2>Votre bibliothèque commence ici</h2><p>Importez un document pour vérifier l’extraction avant de travailler avec vos sources.</p></div>}</section></div>
    </div>
  );
}
