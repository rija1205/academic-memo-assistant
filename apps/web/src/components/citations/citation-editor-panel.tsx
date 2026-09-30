"use client";

import {
  ApiError,
  deleteCitation,
  detachCitationReference,
  patchCitation,
  type Citation,
  type CitationItemInput,
  type LocatorType,
} from "@/lib/api";
import { useCallback, useEffect, useState } from "react";

/**
 * Edit an existing citation: add or remove a reference, change the page, the prefix, the
 * suffix and the mode.
 *
 * The citation is never recreated. The node keeps its `citationId`, so the edit is a PATCH on
 * the same row and the document is not churned.
 */
export function CitationEditorPanel({
  citation,
  onClose,
  onSaved,
  onDeleted,
}: {
  citation: Citation;
  onClose: () => void;
  onSaved: (citation: Citation) => void;
  onDeleted: () => void;
}) {
  const [items, setItems] = useState<CitationItemInput[]>(
    citation.items.map((item) => ({
      reference_id: item.reference_id,
      locator_type: item.locator_type,
      locator_value: item.locator_value,
      prefix: item.prefix,
      suffix: item.suffix,
    })),
  );
  const [prefix, setPrefix] = useState(citation.prefix ?? "");
  const [suffix, setSuffix] = useState(citation.suffix ?? "");
  const [locatorType, setLocatorType] = useState<LocatorType | null>(citation.locator_type);
  const [locatorValue, setLocatorValue] = useState(citation.locator_value ?? "");
  const [mode, setMode] = useState<"parenthetical" | "narrative">(citation.mode);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    setItems(
      citation.items.map((item) => ({
        reference_id: item.reference_id,
        locator_type: item.locator_type,
        locator_value: item.locator_value,
        prefix: item.prefix,
        suffix: item.suffix,
      })),
    );
    setPrefix(citation.prefix ?? "");
    setSuffix(citation.suffix ?? "");
    setLocatorType(citation.locator_type);
    setLocatorValue(citation.locator_value ?? "");
    setMode(citation.mode);
  }, [citation]);

  const refresh = useCallback(
    async (payload: Parameters<typeof patchCitation>[2]) => {
      setBusy(true);
      setError("");
      try {
        const updated = await patchCitation(citation.project_id, citation.id, payload);
        onSaved(updated);
        return updated;
      } catch (cause) {
        setError(cause instanceof ApiError ? cause.message : "Modification impossible.");
        return null;
      } finally {
        setBusy(false);
      }
    },
    [citation.id, citation.project_id, onSaved],
  );

  async function save() {
    await refresh({ items, prefix, suffix, locator_type: locatorType, locator_value: locatorValue || null, mode });
  }

  async function removeItem(referenceId: string) {
    // Detaching keeps the citation alive; only the author removes a reference from it.
    setBusy(true);
    setError("");
    try {
      const updated = await detachCitationReference(citation.project_id, citation.id, referenceId);
      onSaved(updated);
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Suppression impossible.");
    } finally {
      setBusy(false);
    }
  }

  async function move(index: number, delta: number) {
    const next = [...items];
    const target = index + delta;
    if (target < 0 || target >= next.length) return;
    [next[index], next[target]] = [next[target], next[index]];
    setItems(next);
  }

  return (
    <div className="citation-editor" role="dialog" aria-label="Modifier la citation">
      <header className="citation-editor-head">
        <h3>Modifier la citation</h3>
        <code>{citation.citation_key}</code>
      </header>

      <p className="citation-editor-render">
        <strong>Rendu actuel :</strong> {citation.rendered_text}
        {citation.is_stale_snapshot ? (
          <small>
            {" "}
            · le rendu a changé depuis la dernière sauvegarde : la référence a été modifiée.
          </small>
        ) : null}
      </p>

      <ol className="citation-editor-items">
        {items.map((item, index) => (
          <li key={item.reference_id}>
            <span>
              {citation.items.find((entry) => entry.reference_id === item.reference_id)?.title ??
                item.reference_id}
            </span>
            <button
              type="button"
              aria-label="Monter la référence"
              disabled={index === 0 || busy}
              onClick={() => void move(index, -1)}
            >
              ↑
            </button>
            <button
              type="button"
              aria-label="Descendre la référence"
              disabled={index === items.length - 1 || busy}
              onClick={() => void move(index, 1)}
            >
              ↓
            </button>
            <button
              type="button"
              aria-label="Retirer la référence de la citation"
              disabled={busy || items.length === 1}
              onClick={() => void removeItem(item.reference_id)}
            >
              Retirer
            </button>
          </li>
        ))}
      </ol>

      <div className="citation-editor-fields">
        <label>
          <span>Emplacement</span>
          <input
            aria-label="Type d'emplacement"
            placeholder="page, pages, chap., fig., tableau…"
            value={locatorType ?? ""}
            onChange={(event) => setLocatorType(event.target.value as LocatorType | null || null)}
          />
        </label>
        <label>
          <span>Page / valeur</span>
          <input
            aria-label="Valeur de l'emplacement"
            value={locatorValue}
            onChange={(event) => setLocatorValue(event.target.value)}
          />
        </label>
        <label>
          <span>Préfixe</span>
          <input
            aria-label="Préfixe"
            value={prefix}
            onChange={(event) => setPrefix(event.target.value)}
          />
        </label>
        <label>
          <span>Suffixe</span>
          <input
            aria-label="Suffixe"
            value={suffix}
            onChange={(event) => setSuffix(event.target.value)}
          />
        </label>
        <label>
          <span>Mode</span>
          <select
            aria-label="Mode de citation"
            value={mode}
            onChange={(event) => setMode(event.target.value as "parenthetical" | "narrative")}
          >
            <option value="parenthetical">Parenthétique — (Dupont, 2024)</option>
            <option value="narrative">Narrative — Dupont (2024)</option>
          </select>
        </label>
      </div>

      {error ? (
        <p className="form-error" role="alert">
          {error}
        </p>
      ) : null}

      <footer className="citation-editor-actions">
        <button
          className="button button--danger button--small"
          type="button"
          disabled={busy}
          onClick={() => {
            if (!window.confirm("Supprimer cette citation du document ? La référence reste dans la bibliographie.")) {
              return;
            }
            setBusy(true);
            void deleteCitation(citation.project_id, citation.id)
              .then(() => onDeleted())
              .catch((cause: unknown) =>
                setError(cause instanceof ApiError ? cause.message : "Suppression impossible."),
              )
              .finally(() => setBusy(false));
          }}
        >
          Supprimer la citation
        </button>
        <button className="button button--secondary button--small" type="button" onClick={onClose}>
          Fermer
        </button>
        <button
          className="button button--primary button--small"
          type="button"
          disabled={busy}
          onClick={() => void save()}
        >
          Enregistrer
        </button>
      </footer>
    </div>
  );
}
