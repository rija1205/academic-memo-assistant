"use client";

import {
  ApiError,
  createBibliographyReference,
  deleteBibliographyReference,
  exportBibliographyUrl,
  getBibliographyDuplicates,
  getBibliographyStats,
  getRenderedBibliography,
  importBibliographyFile,
  listBibliography,
  type RenderedBibliography,
  mergeBibliographyReference,
  updateBibliographyReference,
  type BibliographyDuplicateReport,
  type BibliographyReference,
  type BibliographyReferenceInput,
  type BibliographyStats,
  type ReferenceType,
} from "@/lib/api";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";

const TYPE_LABELS: Record<ReferenceType, string> = {
  article: "Article",
  book: "Livre",
  book_chapter: "Chapitre",
  thesis: "Thèse",
  report: "Rapport",
  conference: "Conférence",
  webpage: "Site web",
  dataset: "Jeu de données",
  patent: "Brevet",
  other: "Autre",
};

const FIELD_LABELS: Record<string, string> = {
  title: "Titre",
  publication_year: "Année",
  doi: "DOI",
  journal: "Revue",
  volume: "Volume",
  issue: "Numéro",
  pages: "Pages",
  publisher: "Éditeur",
  url: "URL",
  abstract: "Résumé",
  isbn: "ISBN",
};

const emptyDraft: BibliographyReferenceInput = {
  reference_type: "article",
  title: null,
  authors: [],
  keywords: [],
  tags: [],
};

export function BibliographyWorkspace({
  projectId,
  canEdit,
  canDelete,
}: {
  projectId: string;
  canEdit: boolean;
  canDelete: boolean;
}) {
  const [references, setReferences] = useState<BibliographyReference[]>([]);
  const [total, setTotal] = useState(0);
  const [stats, setStats] = useState<BibliographyStats | null>(null);
  const [query, setQuery] = useState("");
  const [typeFilter, setTypeFilter] = useState<ReferenceType | "">("");
  const [yearFilter, setYearFilter] = useState("");
  const [authorFilter, setAuthorFilter] = useState("");
  const [doiFilter, setDoiFilter] = useState<"" | "with" | "without">("");
  const [sourceFilter, setSourceFilter] = useState<"" | "with" | "without">("");
  const [selected, setSelected] = useState<BibliographyReference | null>(null);
  const [draft, setDraft] = useState<BibliographyReferenceInput>(emptyDraft);
  const [editing, setEditing] = useState(false);
  const [duplicates, setDuplicates] = useState<BibliographyDuplicateReport | null>(null);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  // Stage 10: the final bibliography only contains the references that are actually cited.
  const [rendered, setRendered] = useState<RenderedBibliography | null>(null);
  const [showUncited, setShowUncited] = useState(false);

  const load = useCallback(async () => {
    setBusy(true);
    try {
      const [list, nextStats, nextRendered] = await Promise.all([
        listBibliography(projectId, {
          q: query || undefined,
          reference_type: typeFilter || undefined,
          year: yearFilter ? Number(yearFilter) : undefined,
          author: authorFilter || undefined,
          has_doi: doiFilter === "with" ? true : doiFilter === "without" ? false : undefined,
          has_source: sourceFilter === "with" ? true : sourceFilter === "without" ? false : undefined,
          limit: 100,
        }),
        getBibliographyStats(projectId),
        getRenderedBibliography(projectId).catch(() => null),
      ]);
      setReferences(list.items);
      setTotal(list.total);
      setStats(nextStats);
      setRendered(nextRendered);
      setError("");
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Bibliographie indisponible.");
    } finally {
      setBusy(false);
    }
  }, [authorFilter, doiFilter, projectId, query, sourceFilter, typeFilter, yearFilter]);

  useEffect(() => {
    void load();
  }, [load]);

  const years = useMemo(
    () => Object.keys(stats?.by_year ?? {}).sort((a, b) => Number(b) - Number(a)),
    [stats],
  );

  function toggleSelection(id: string) {
    setSelectedIds((current) =>
      current.includes(id) ? current.filter((item) => item !== id) : [...current, id],
    );
  }

  async function open(reference: BibliographyReference) {
    setSelected(reference);
    setEditing(false);
    setDuplicates(null);
    setDraft({
      reference_type: reference.reference_type,
      citation_key: reference.citation_key,
      title: reference.title,
      subtitle: reference.subtitle,
      authors: reference.authors.map((author) => ({
        given_name: author.given_name,
        family_name: author.family_name,
        orcid: author.orcid,
      })),
      publication_year: reference.publication_year,
      publication_month: reference.publication_month,
      publication_day: reference.publication_day,
      doi: reference.doi_original ?? reference.doi,
      url: reference.url,
      accessed_at: reference.accessed_at,
      journal: reference.journal,
      volume: reference.volume,
      issue: reference.issue,
      pages: reference.pages,
      publisher: reference.publisher,
      publisher_place: reference.publisher_place,
      edition: reference.edition,
      isbn: reference.isbn,
      issn: reference.issn,
      abstract: reference.abstract,
      keywords: reference.keywords,
      language: reference.language,
      notes: reference.notes,
      source_id: reference.source_id,
      tags: reference.tags,
    });
    try {
      setDuplicates(await getBibliographyDuplicates(projectId, reference.id));
    } catch {
      setDuplicates(null);
    }
  }

  function startCreate() {
    setSelected(null);
    setDuplicates(null);
    setDraft(emptyDraft);
    setEditing(true);
  }

  async function save() {
    if (!selected && !editing) return;
    setBusy(true);
    setError("");
    try {
      if (selected) {
        const updated = await updateBibliographyReference(projectId, selected.id, draft);
        setSelected(updated);
      } else {
        const created = await createBibliographyReference(projectId, draft);
        setSelected(created);
      }
      setEditing(false);
      await load();
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Enregistrement impossible.");
    } finally {
      setBusy(false);
    }
  }

  async function remove(reference: BibliographyReference) {
    if (!window.confirm(`Supprimer la référence « ${reference.citation_key} » ?`)) return;
    try {
      await deleteBibliographyReference(projectId, reference.id);
      setSelected(null);
      await load();
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Suppression impossible.");
    }
  }

  async function doImport(format: "bibtex" | "ris") {
    const input = document.createElement("input");
    input.type = "file";
    input.accept = format === "bibtex" ? ".bib,.bibtex,text/plain" : ".ris,text/plain";
    input.onchange = () => {
      const file = input.files?.[0];
      if (!file) return;
      setBusy(true);
      setNotice("");
      void importBibliographyFile(projectId, format, file)
        .then((result) => {
          setNotice(
            `${result.imported} référence(s) importée(s), ${result.duplicates} doublon(s) détecté(s), ` +
              `${result.skipped} ignorée(s).`,
          );
          return load();
        })
        .catch((cause: unknown) => {
          setError(cause instanceof ApiError ? cause.message : "Import impossible.");
        })
        .finally(() => setBusy(false));
    };
    input.click();
  }

  async function merge(duplicateId: string, keepId: string) {
    if (!window.confirm("Fusionner ce doublon dans la référence conservée ?")) return;
    try {
      const merged = await mergeBibliographyReference(projectId, duplicateId, keepId);
      setSelected(merged);
      setNotice("Doublon fusionné : aucune information n'a été perdue.");
      await load();
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Fusion impossible.");
    }
  }

  return (
    <div className="bibliography-page">
      <header className="bibliography-heading">
        <div>
          <p className="eyebrow">Références</p>
          <h1>Bibliographie</h1>
          <p>
            Les références sont indépendantes des fichiers importés. Une source téléchargée
            n&apos;est pas automatiquement une référence, et une référence peut exister sans
            fichier local.
          </p>
        </div>
        <div className="bibliography-heading-actions">
          {canEdit ? (
            <>
              <button className="button button--primary" type="button" onClick={startCreate}>
                + Ajouter une référence
              </button>
              <button className="button button--secondary" type="button" onClick={() => void doImport("bibtex")} disabled={busy}>
                Importer BibTeX
              </button>
              <button className="button button--secondary" type="button" onClick={() => void doImport("ris")} disabled={busy}>
                Importer RIS
              </button>
            </>
          ) : null}
          <a
            className="button button--secondary"
            href={exportBibliographyUrl(projectId, "bibtex", selectedIds)}
          >
            Exporter BibTeX
          </a>
          <a
            className="button button--secondary"
            href={exportBibliographyUrl(projectId, "ris", selectedIds)}
          >
            Exporter RIS
          </a>
        </div>
      </header>

      {stats ? (
        <dl className="bibliography-stats">
          <div><dt>Références</dt><dd>{stats.total}</dd></div>
          {Object.entries(stats.by_type).slice(0, 4).map(([type, count]) => (
            <div key={type}><dt>{TYPE_LABELS[type as ReferenceType] ?? type}</dt><dd>{count}</dd></div>
          ))}
          <div><dt>Avec DOI</dt><dd>{stats.with_doi}</dd></div>
          <div><dt>Avec fichier</dt><dd>{stats.with_source}</dd></div>
        </dl>
      ) : null}

      {rendered ? (
        <section className="bibliography-citation-status">
          <div className="bibliography-citation-counts">
            <div>
              <dt>R?f?rences cit?es</dt>
              <dd>{rendered.cited_count}</dd>
            </div>
            <div>
              <dt>R?f?rences non cit?es</dt>
              <dd>{rendered.uncited_count}</dd>
            </div>
            <div>
              <dt>Citations invalides</dt>
              <dd>{rendered.orphaned_citations.length}</dd>
            </div>
            <div>
              <dt>Style</dt>
              <dd>{rendered.style_label}</dd>
            </div>
          </div>
          <p className="bibliography-citation-hint">
            Une r?f?rence pr?sente dans la biblioth?que n&apos;entre pas automatiquement dans la
            bibliographie finale : seules les r?f?rences effectivement cit?es dans le m?moire y
            figurent.
            {rendered.incomplete_count > 0
              ? ` ${rendered.incomplete_count} entr?e(s) signalent une information manquante.`
              : ""}
          </p>
          {rendered.orphaned_citations.length > 0 ? (
            <ul className="bibliography-orphans">
              {rendered.orphaned_citations.map((orphan) => (
                <li key={orphan.citation_id}>
                  <strong>Citation invalide</strong> ? {orphan.message}
                  {orphan.snapshot_text ? (
                    <small> Dernier rendu connu : {orphan.snapshot_text}</small>
                  ) : null}
                </li>
              ))}
            </ul>
          ) : null}
          {rendered.uncited_count > 0 ? (
            <>
              <button
                className="button button--secondary button--small"
                type="button"
                onClick={() => setShowUncited((value) => !value)}
              >
                {showUncited ? "Masquer" : "Afficher"} les r?f?rences non cit?es
              </button>
              {showUncited ? (
                <ul className="bibliography-uncited">
                  {rendered.uncited.map((reference) => (
                    <li key={reference.reference_id}>
                      <span>
                        {reference.citation_key}
                        {reference.publication_year ? ` ? ${reference.publication_year}` : " ? ann?e non renseign?e"}
                      </span>
                      <small>{reference.title ?? "Titre non renseign?"}</small>
                    </li>
                  ))}
                </ul>
              ) : null}
            </>
          ) : null}
        </section>
      ) : null}

      <div className="bibliography-toolbar">
        <input
          aria-label="Rechercher une référence"
          placeholder="Rechercher : titre, auteur, DOI, revue, mots-clés…"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
        />
        <select
          aria-label="Filtrer par type"
          value={typeFilter}
          onChange={(event) => setTypeFilter(event.target.value as ReferenceType | "")}
        >
          <option value="">Tous les types</option>
          {Object.entries(TYPE_LABELS).map(([value, label]) => (
            <option key={value} value={value}>{label}</option>
          ))}
        </select>
        <select
          aria-label="Filtrer par année"
          value={yearFilter}
          onChange={(event) => setYearFilter(event.target.value)}
        >
          <option value="">Toutes les années</option>
          {years.map((year) => (
            <option key={year} value={year}>{year}</option>
          ))}
        </select>
        <input
          aria-label="Filtrer par auteur"
          placeholder="Auteur"
          value={authorFilter}
          onChange={(event) => setAuthorFilter(event.target.value)}
        />
        <select
          aria-label="Filtrer par DOI"
          value={doiFilter}
          onChange={(event) => setDoiFilter(event.target.value as "" | "with" | "without")}
        >
          <option value="">DOI : tous</option>
          <option value="with">Avec DOI</option>
          <option value="without">Sans DOI</option>
        </select>
        <select
          aria-label="Filtrer par fichier"
          value={sourceFilter}
          onChange={(event) => setSourceFilter(event.target.value as "" | "with" | "without")}
        >
          <option value="">Fichier : tous</option>
          <option value="with">Avec fichier</option>
          <option value="without">Sans fichier</option>
        </select>
      </div>

      {notice ? <p className="bibliography-notice">{notice}</p> : null}
      {error ? <p className="form-error" role="alert">{error}</p> : null}

      <div className="bibliography-layout">
        <section className="bibliography-list-panel">
          <div className="panel-heading">
            <h2>Références ({total})</h2>
            {selectedIds.length > 0 ? <span>{selectedIds.length} sélectionnée(s)</span> : null}
          </div>
          {busy && references.length === 0 ? <p className="empty-panel">Chargement…</p> : null}
          {!busy && references.length === 0 ? (
            <p className="empty-panel">
              Aucune référence. Ajoutez-en une ou importez un fichier BibTeX / RIS.
            </p>
          ) : null}
          <div className="bibliography-list">
            {references.map((reference) => (
              <article
                key={reference.id}
                className={`bibliography-row ${selected?.id === reference.id ? "selected" : ""}`}
              >
                <label className="bibliography-row-select">
                  <input
                    type="checkbox"
                    checked={selectedIds.includes(reference.id)}
                    onChange={() => toggleSelection(reference.id)}
                    aria-label={`Sélectionner ${reference.citation_key}`}
                  />
                </label>
                <button type="button" className="bibliography-row-main" onClick={() => void open(reference)}>
                  <strong>{reference.title || "Titre non renseigné"}</strong>
                  <span>
                    {reference.authors.length > 0
                      ? reference.authors.map((author) => author.family_name).join(", ")
                      : "Auteur non renseigné"}
                    {reference.publication_year ? ` (${reference.publication_year})` : " · année non renseignée"}
                  </span>
                  <small>
                    {TYPE_LABELS[reference.reference_type]}
                    {reference.doi ? ` · ${reference.doi}` : " · DOI non renseigné"}
                    {reference.has_source ? " · fichier lié" : " · sans fichier"}
                  </small>
                </button>
              </article>
            ))}
          </div>
        </section>

        <section className="bibliography-detail-panel">
          {selected ? (
            <>
              <div className="bibliography-detail-head">
                <div>
                  <code className="bibliography-key">{selected.citation_key}</code>
                  <h2>{selected.title || "Titre non renseigné"}</h2>
                </div>
                {canEdit ? (
                  <div className="bibliography-detail-actions">
                    <button
                      className="button button--secondary button--small"
                      type="button"
                      onClick={() => setEditing((value) => !value)}
                    >
                      {editing ? "Annuler" : "Modifier"}
                    </button>
                    {canDelete ? (
                      <button
                        className="button button--danger button--small"
                        type="button"
                        onClick={() => void remove(selected)}
                      >
                        Supprimer
                      </button>
                    ) : null}
                  </div>
                ) : null}
              </div>

              {duplicates?.has_duplicates ? (
                <div className="bibliography-duplicates">
                  <h3>Doublon possible</h3>
                  {[...duplicates.exact, ...duplicates.strong, ...duplicates.possible].map((match) => (
                    <div key={match.reference_id} className="bibliography-duplicate">
                      <span className={`duplicate-level duplicate-level--${match.level}`}>
                        {match.level === "exact" ? "Exact" : match.level === "strong" ? "Fort" : "Possible"}
                      </span>
                      <p>{match.title || match.citation_key}</p>
                      <small>{match.reason}</small>
                      {canEdit ? (
                        <button
                          type="button"
                          className="button button--secondary button--small"
                          onClick={() => void merge(match.reference_id, selected.id)}
                        >
                          Fusionner dans celle-ci
                        </button>
                      ) : null}
                    </div>
                  ))}
                </div>
              ) : null}

              {editing ? (
                <ReferenceForm draft={draft} onChange={setDraft} />
              ) : (
                <ReferenceDetail reference={selected} projectId={projectId} />
              )}

              {editing ? (
                <div className="form-actions">
                  <button className="button button--primary button--small" type="button" onClick={() => void save()} disabled={busy}>
                    Enregistrer
                  </button>
                </div>
              ) : null}
            </>
          ) : editing ? (
            <>
              <h2>Nouvelle référence</h2>
              <ReferenceForm draft={draft} onChange={setDraft} />
              <div className="form-actions">
                <button className="button button--primary button--small" type="button" onClick={() => void save()} disabled={busy}>
                  Créer la référence
                </button>
              </div>
            </>
          ) : (
            <div className="empty-panel">
              <span className="empty-icon">▤</span>
              <h2>Sélectionnez une référence</h2>
              <p>
                Les champs non renseignés restent affichés comme « Non renseigné » : aucune
                donnée n&apos;est inventée.
              </p>
            </div>
          )}
        </section>
      </div>
    </div>
  );
}

function ReferenceDetail({
  reference,
  projectId,
}: {
  reference: BibliographyReference;
  projectId: string;
}) {
  const missing = reference.missing_fields.map((field) => FIELD_LABELS[field] ?? field);
  return (
    <div className="bibliography-detail">
      <dl className="bibliography-fields">
        <div><dt>Auteurs</dt><dd>{reference.authors.length > 0 ? reference.authors.map((author) => `${author.given_name ?? ""} ${author.family_name}`.trim()).join(", ") : "Non renseigné"}</dd></div>
        <div><dt>Type</dt><dd>{TYPE_LABELS[reference.reference_type]}</dd></div>
        <div><dt>Revue</dt><dd>{reference.journal ?? "Non renseigné"}</dd></div>
        <div><dt>Volume</dt><dd>{reference.volume ?? "Non renseigné"}</dd></div>
        <div><dt>Numéro</dt><dd>{reference.issue ?? "Non renseigné"}</dd></div>
        <div><dt>Pages</dt><dd>{reference.pages ?? "Non renseigné"}</dd></div>
        <div><dt>Éditeur</dt><dd>{reference.publisher ?? "Non renseigné"}</dd></div>
        <div><dt>DOI</dt><dd>{reference.doi ? <a href={`https://doi.org/${reference.doi}`} target="_blank" rel="noreferrer">{reference.doi}</a> : "Non renseigné"}</dd></div>
        <div><dt>URL</dt><dd>{reference.url ? <a href={reference.url} target="_blank" rel="noreferrer">{reference.url}</a> : "Non renseigné"}</dd></div>
        <div><dt>ISBN</dt><dd>{reference.isbn ?? "Non renseigné"}</dd></div>
        <div><dt>ISSN</dt><dd>{reference.issn ?? "Non renseigné"}</dd></div>
        <div><dt>Mots-clés</dt><dd>{reference.keywords.length > 0 ? reference.keywords.join(", ") : "Non renseigné"}</dd></div>
        <div><dt>Tags</dt><dd>{reference.tags.length > 0 ? reference.tags.join(", ") : "Aucun"}</dd></div>
        <div>
          <dt>Source liée</dt>
          <dd>
            {reference.has_source ? (
              <Link href={`/projects/${projectId}/sources?source=${reference.source_id}`}>
                {reference.source_title || "Voir la source"}
              </Link>
            ) : (
              "Aucune source liée"
            )}
          </dd>
        </div>
        <div><dt>Résumé</dt><dd>{reference.abstract || "Non renseigné"}</dd></div>
        <div><dt>Notes</dt><dd>{reference.notes || "Non renseigné"}</dd></div>
      </dl>
      {missing.length > 0 ? (
        <p className="bibliography-missing">
          Informations manquantes : {missing.join(", ")}
        </p>
      ) : (
        <p className="bibliography-complete">Toutes les informations principales sont renseignées.</p>
      )}
    </div>
  );
}

function ReferenceForm({
  draft,
  onChange,
}: {
  draft: BibliographyReferenceInput;
  onChange: (value: BibliographyReferenceInput) => void;
}) {
  const set = <K extends keyof BibliographyReferenceInput>(
    key: K,
    value: BibliographyReferenceInput[K],
  ) => onChange({ ...draft, [key]: value });
  const authors = draft.authors ?? [];
  return (
    <div className="bibliography-form">
      <label className="auth-field">
        <span>Titre</span>
        <input value={draft.title ?? ""} onChange={(event) => set("title", event.target.value || null)} />
      </label>
      <label className="auth-field">
        <span>Type</span>
        <select value={draft.reference_type ?? "other"} onChange={(event) => set("reference_type", event.target.value as ReferenceType)}>
          {Object.entries(TYPE_LABELS).map(([value, label]) => (
            <option key={value} value={value}>{label}</option>
          ))}
        </select>
      </label>
      <label className="auth-field">
        <span>Année</span>
        <input type="number" value={draft.publication_year ?? ""} onChange={(event) => set("publication_year", event.target.value ? Number(event.target.value) : null)} />
      </label>
      <label className="auth-field">
        <span>DOI</span>
        <input value={draft.doi ?? ""} onChange={(event) => set("doi", event.target.value || null)} placeholder="10.1234/exemple" />
      </label>
      <label className="auth-field">
        <span>Revue</span>
        <input value={draft.journal ?? ""} onChange={(event) => set("journal", event.target.value || null)} />
      </label>
      <label className="auth-field">
        <span>Volume</span>
        <input value={draft.volume ?? ""} onChange={(event) => set("volume", event.target.value || null)} />
      </label>
      <label className="auth-field">
        <span>Numéro</span>
        <input value={draft.issue ?? ""} onChange={(event) => set("issue", event.target.value || null)} />
      </label>
      <label className="auth-field">
        <span>Pages</span>
        <input value={draft.pages ?? ""} onChange={(event) => set("pages", event.target.value || null)} />
      </label>
      <label className="auth-field">
        <span>Éditeur</span>
        <input value={draft.publisher ?? ""} onChange={(event) => set("publisher", event.target.value || null)} />
      </label>
      <label className="auth-field">
        <span>URL</span>
        <input value={draft.url ?? ""} onChange={(event) => set("url", event.target.value || null)} />
      </label>
      <div className="bibliography-form-wide">
        <span className="auth-field-label">Auteurs (un par ligne : Nom, Prénom)</span>
        <textarea
          rows={4}
          value={authors.map((author) => (author.given_name ? `${author.family_name}, ${author.given_name}` : author.family_name)).join("\n")}
          onChange={(event) => {
            const lines = event.target.value.split("\n").map((line) => line.trim()).filter(Boolean);
            set("authors", lines.map((line) => {
              const [family, given] = line.includes(",") ? line.split(",") : [line, ""];
              return { family_name: family.trim(), given_name: given.trim() || null };
            }));
          }}
        />
      </div>
      <label className="auth-field bibliography-form-wide">
        <span>Mots-clés (séparés par des virgules)</span>
        <input value={(draft.keywords ?? []).join(", ")} onChange={(event) => set("keywords", event.target.value.split(",").map((value) => value.trim()).filter(Boolean))} />
      </label>
      <label className="auth-field bibliography-form-wide">
        <span>Tags du projet (séparés par des virgules)</span>
        <input value={(draft.tags ?? []).join(", ")} onChange={(event) => set("tags", event.target.value.split(",").map((value) => value.trim()).filter(Boolean))} />
      </label>
      <label className="auth-field bibliography-form-wide">
        <span>Résumé</span>
        <textarea rows={3} value={draft.abstract ?? ""} onChange={(event) => set("abstract", event.target.value || null)} />
      </label>
      <label className="auth-field bibliography-form-wide">
        <span>Notes</span>
        <textarea rows={2} value={draft.notes ?? ""} onChange={(event) => set("notes", event.target.value || null)} />
      </label>
    </div>
  );
}
