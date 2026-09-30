"use client";

import {
  ApiError,
  listBibliography,
  previewCitation,
  type BibliographyReference,
  type CitationItemInput,
  type CitationMode,
  type CitationPreview,
  type LocatorType,
} from "@/lib/api";
import { useCallback, useEffect, useMemo, useState } from "react";

const LOCATOR_LABELS: Record<LocatorType, string> = {
  page: "p.",
  pages: "pp.",
  chapter: "chap.",
  figure: "fig.",
  table: "tableau",
  section: "sec.",
  other: "autre",
};

const LOCATOR_OPTIONS: LocatorType[] = [
  "page",
  "pages",
  "chapter",
  "figure",
  "table",
  "section",
  "other",
];

function authorLabel(reference: BibliographyReference): string {
  if (reference.authors.length === 0) return "Auteur non renseigné";
  const first = reference.authors[0];
  const given = first.given_name ? `${first.given_name} ` : "";
  const others = reference.authors.length - 1;
  return `${given}${first.family_name}${others > 0 ? ` et al. (+${others})` : ""}`;
}

/**
 * Reference picker for a citation.
 *
 * The preview is fetched from the same endpoint that renders the document, so what the author
 * sees before inserting is exactly what will be displayed. The component never formats a
 * citation itself: there is one style engine, on the server.
 */
export function CitationPicker({
  projectId,
  mode = "parenthetical",
  initialReferenceIds = [],
  initialPrefix = "",
  initialSuffix = "",
  initialLocatorType = null,
  initialLocatorValue = "",
  onConfirm,
  onCancel,
}: {
  projectId: string;
  mode?: CitationMode;
  initialReferenceIds?: string[];
  initialPrefix?: string;
  initialSuffix?: string;
  initialLocatorType?: LocatorType | null;
  initialLocatorValue?: string;
  onConfirm: (input: {
    items: CitationItemInput[];
    prefix: string;
    suffix: string;
    locatorType: LocatorType | null;
    locatorValue: string;
    mode: CitationMode;
    preview: CitationPreview;
  }) => void;
  onCancel: () => void;
}) {
  const [references, setReferences] = useState<BibliographyReference[]>([]);
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<string[]>(initialReferenceIds);
  const [locatorType, setLocatorType] = useState<LocatorType | null>(initialLocatorType);
  const [locatorValue, setLocatorValue] = useState(initialLocatorValue);
  const [prefix, setPrefix] = useState(initialPrefix);
  const [suffix, setSuffix] = useState(initialSuffix);
  const [preview, setPreview] = useState<CitationPreview | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    try {
      const result = await listBibliography(projectId, {
        q: query || undefined,
        limit: 60,
      });
      setReferences(result.items);
      setError("");
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Bibliographie indisponible.");
    }
  }, [projectId, query]);

  useEffect(() => {
    void load();
  }, [load]);

  const items = useMemo<CitationItemInput[]>(
    () =>
      // The order of the checkboxes is the order of the references inside the citation. The
      // server assigns the positions, so they are not sent from here.
      selected.map((referenceId) => ({
        reference_id: referenceId,
        // The locator typed once applies to every reference, as APA and Harvard do.
        locator_type: locatorType,
        locator_value: locatorValue.trim() || null,
      })),
    [locatorType, locatorValue, selected],
  );

  useEffect(() => {
    if (items.length === 0) {
      setPreview(null);
      return;
    }
    let cancelled = false;
    const handle = setTimeout(() => {
      void previewCitation(projectId, { items, prefix, suffix, mode })
        .then((result) => {
          if (!cancelled) {
            setPreview(result);
            setError("");
          }
        })
        .catch((cause: unknown) => {
          if (!cancelled) setError(cause instanceof ApiError ? cause.message : "Aperçu impossible.");
        });
    }, 180);
    return () => {
      cancelled = true;
      clearTimeout(handle);
    };
  }, [items, mode, prefix, projectId, suffix]);

  function toggle(referenceId: string) {
    setSelected((current) =>
      current.includes(referenceId)
        ? current.filter((item) => item !== referenceId)
        : [...current, referenceId],
    );
  }

  return (
    <div className="citation-picker" role="dialog" aria-label="Insérer une citation">
      <header className="citation-picker-head">
        <h3>Insérer une citation</h3>
        <span>
          {selected.length} référence{selected.length > 1 ? "s" : ""} sélectionnée
          {selected.length > 1 ? "s" : ""}
        </span>
      </header>

      <input
        className="citation-picker-search"
        aria-label="Rechercher une référence"
        placeholder="Rechercher : auteur, titre, année, DOI, revue, mots-clés…"
        value={query}
        onChange={(event) => setQuery(event.target.value)}
      />

      <div className="citation-picker-list" role="listbox" aria-multiselectable>
        {references.length === 0 ? (
          <p className="empty-panel">Aucune référence. Ajoutez-en une dans la bibliographie.</p>
        ) : null}
        {references.map((reference) => {
          const isSelected = selected.includes(reference.id);
          return (
            <label
              key={reference.id}
              className={`citation-picker-item ${isSelected ? "selected" : ""}`}
            >
              <input
                type="checkbox"
                checked={isSelected}
                onChange={() => toggle(reference.id)}
                aria-label={`Sélectionner ${reference.citation_key}`}
              />
              <span className="citation-picker-item-body">
                <strong>
                  {authorLabel(reference)}
                  {reference.publication_year ? ` — ${reference.publication_year}` : " — année non renseignée"}
                </strong>
                <span>{reference.title ?? "Titre non renseigné"}</span>
                <small>
                  {reference.doi ? reference.doi : "DOI non renseigné"}
                  {reference.journal ? ` · ${reference.journal}` : ""}
                </small>
              </span>
            </label>
          );
        })}
      </div>

      <div className="citation-picker-fields">
        <label>
          <span>Emplacement</span>
          <select
            aria-label="Type d'emplacement"
            value={locatorType ?? ""}
            onChange={(event) =>
              setLocatorType(event.target.value === "" ? null : (event.target.value as LocatorType))
            }
          >
            <option value="">Aucun</option>
            {LOCATOR_OPTIONS.map((option) => (
              <option key={option} value={option}>
                {LOCATOR_LABELS[option]}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>Page / valeur</span>
          <input
            aria-label="Valeur de l'emplacement"
            placeholder="25 ou 25-28"
            value={locatorValue}
            onChange={(event) => setLocatorValue(event.target.value)}
          />
        </label>
        <label>
          <span>Préfixe</span>
          <input
            aria-label="Préfixe de la citation"
            placeholder="Voir "
            value={prefix}
            onChange={(event) => setPrefix(event.target.value)}
          />
        </label>
        <label>
          <span>Suffixe</span>
          <input
            aria-label="Suffixe de la citation"
            placeholder=", p. 25"
            value={suffix}
            onChange={(event) => setSuffix(event.target.value)}
          />
        </label>
      </div>

      {preview ? (
        <div className="citation-picker-preview">
          <p>
            <strong>Aperçu de la citation :</strong> {preview.citation}
          </p>
          <p>
            <strong>Entrée bibliographique :</strong> {preview.bibliography_entry}
          </p>
          <small>
            Style {preview.style_label} · moteur de rendu du serveur
          </small>
          {preview.warnings.length > 0 ? (
            <ul className="citation-picker-warnings">
              {preview.warnings.map((warning) => (
                <li key={warning}>{warning}</li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}

      {error ? (
        <p className="form-error" role="alert">
          {error}
        </p>
      ) : null}

      <footer className="citation-picker-actions">
        <button className="button button--secondary button--small" type="button" onClick={onCancel}>
          Annuler
        </button>
        <button
          className="button button--primary button--small"
          type="button"
          disabled={busy || items.length === 0}
          onClick={() =>
            onConfirm({
              items,
              prefix,
              suffix,
              locatorType,
              locatorValue,
              mode,
              preview: preview as CitationPreview,
            })
          }
        >
          Insérer
        </button>
      </footer>
    </div>
  );
}
