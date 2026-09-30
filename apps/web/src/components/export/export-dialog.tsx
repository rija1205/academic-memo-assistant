"use client";

import {
  ApiError,
  downloadExport,
  getExportCatalogue,
  listExports,
  previewExport,
  type ExportCatalogue,
  type ExportFormat,
  type ExportOptions,
  type ExportPreview,
  type ExportRecord,
} from "@/lib/api";
import { useCallback, useEffect, useState } from "react";

const DEFAULTS: ExportOptions = {
  page_size: "a4",
  orientation: "portrait",
  font_family: "times",
  font_size: 12,
  line_spacing: 1.5,
  first_line_indent: 1.25,
  paragraph_alignment: "justify",
  include_cover: true,
  include_toc: true,
  include_list_of_figures: true,
  include_list_of_tables: true,
  include_bibliography: true,
  include_annexes: true,
  include_page_numbers: true,
  roman_front_matter: true,
  number_headings: true,
  embed_remote_images: false,
};

function humanSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} o`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} Ko`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} Mo`;
}

/**
 * The export dialog.
 *
 * The preview is fetched from the server, which runs the same citation engine as the editor,
 * so the counts and the warnings shown here are the ones the file will really contain. Nothing
 * is assembled in the browser: the file comes from the API.
 */
export function ExportDialog({
  projectId,
  onClose,
}: {
  projectId: string;
  onClose: () => void;
}) {
  const [format, setFormat] = useState<ExportFormat>("pdf");
  const [options, setOptions] = useState<ExportOptions>(DEFAULTS);
  const [catalogue, setCatalogue] = useState<ExportCatalogue | null>(null);
  const [preview, setPreview] = useState<ExportPreview | null>(null);
  const [history, setHistory] = useState<ExportRecord[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  useEffect(() => {
    void getExportCatalogue(projectId)
      .then(setCatalogue)
      .catch(() => setCatalogue(null));
    void listExports(projectId)
      .then((result) => setHistory(result.items))
      .catch(() => setHistory([]));
  }, [projectId]);

  const refreshPreview = useCallback(() => {
    let cancelled = false;
    const handle = setTimeout(() => {
      void previewExport(projectId, format, options)
        .then((result) => {
          if (!cancelled) {
            setPreview(result);
            setError("");
          }
        })
        .catch((cause: unknown) => {
          if (!cancelled) {
            setPreview(null);
            setError(cause instanceof ApiError ? cause.message : "Aperçu impossible.");
          }
        });
    }, 250);
    return () => {
      cancelled = true;
      clearTimeout(handle);
    };
  }, [format, options, projectId]);

  useEffect(() => refreshPreview(), [refreshPreview]);

  const set = <K extends keyof ExportOptions>(key: K, value: ExportOptions[K]) => {
    setOptions((current) => ({ ...current, [key]: value }));
  };

  async function run() {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const result = await downloadExport(projectId, format, options);
      setNotice(`${result.fileName} · ${humanSize(result.size)}`);
      const refreshed = await listExports(projectId);
      setHistory(refreshed.items);
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Export impossible.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="export-dialog" role="dialog" aria-label="Exporter le mémoire">
      <header className="export-dialog-head">
        <h2>Exporter le mémoire</h2>
        <button type="button" className="button button--secondary button--small" onClick={onClose}>
          Fermer
        </button>
      </header>

      <div className="export-formats" role="radiogroup" aria-label="Format">
        {(catalogue?.formats ?? [
          { format: "pdf" as ExportFormat, label: "PDF", extension: "pdf", media_type: "" },
          {
            format: "docx" as ExportFormat,
            label: "Word (DOCX)",
            extension: "docx",
            media_type: "",
          },
        ]).map((item) => (
          <label key={item.format} className={`export-format ${format === item.format ? "selected" : ""}`}>
            <input
              type="radio"
              name="export-format"
              value={item.format}
              checked={format === item.format}
              onChange={() => setFormat(item.format)}
            />
            <span>{item.label}</span>
          </label>
        ))}
      </div>

      <div className="export-grid">
        <label>
          <span>Format de page</span>
          <select
            value={options.page_size}
            onChange={(event) => set("page_size", event.target.value as ExportOptions["page_size"])}
          >
            <option value="a4">A4</option>
            <option value="letter">Letter</option>
          </select>
        </label>
        <label>
          <span>Orientation</span>
          <select
            value={options.orientation}
            onChange={(event) =>
              set("orientation", event.target.value as ExportOptions["orientation"])
            }
          >
            <option value="portrait">Portrait</option>
            <option value="landscape">Paysage</option>
          </select>
        </label>
        <label>
          <span>Police</span>
          <select
            value={options.font_family}
            onChange={(event) =>
              set("font_family", event.target.value as ExportOptions["font_family"])
            }
          >
            <option value="times">Times New Roman</option>
            <option value="helvetica">Arial</option>
            <option value="courier">Courier New</option>
          </select>
        </label>
        <label>
          <span>Taille ({options.font_size} pt)</span>
          <input
            type="range"
            min={8}
            max={16}
            step={0.5}
            value={options.font_size}
            onChange={(event) => set("font_size", Number(event.target.value))}
          />
        </label>
        <label>
          <span>Interligne ({options.line_spacing})</span>
          <input
            type="range"
            min={1}
            max={2.5}
            step={0.1}
            value={options.line_spacing}
            onChange={(event) => set("line_spacing", Number(event.target.value))}
          />
        </label>
        <label>
          <span>Retrait du 1er paragraphe ({options.first_line_indent} cm)</span>
          <input
            type="range"
            min={0}
            max={2.5}
            step={0.25}
            value={options.first_line_indent}
            onChange={(event) => set("first_line_indent", Number(event.target.value))}
          />
        </label>
        <label>
          <span>Alignement</span>
          <select
            value={options.paragraph_alignment}
            onChange={(event) =>
              set(
                "paragraph_alignment",
                event.target.value as ExportOptions["paragraph_alignment"],
              )
            }
          >
            <option value="justify">Justifié</option>
            <option value="left">À gauche</option>
            <option value="center">Centré</option>
            <option value="right">À droite</option>
          </select>
        </label>
        <label>
          <span>Marge gauche / droite (cm)</span>
          <span className="export-pair">
            <input
              type="number"
              min={0.5}
              max={8}
              step={0.1}
              value={options.margin_left ?? 3}
              onChange={(event) => set("margin_left", Number(event.target.value))}
            />
            <input
              type="number"
              min={0.5}
              max={8}
              step={0.1}
              value={options.margin_right ?? 2.5}
              onChange={(event) => set("margin_right", Number(event.target.value))}
            />
          </span>
        </label>
      </div>

      <fieldset className="export-toggles">
        <legend>Contenu</legend>
        {(
          [
            ["include_cover", "Page de couverture"],
            ["include_toc", "Table des matières"],
            ["include_list_of_figures", "Liste des figures"],
            ["include_list_of_tables", "Liste des tableaux"],
            ["include_bibliography", "Bibliographie"],
            ["include_annexes", "Annexes"],
            ["include_page_numbers", "Numérotation des pages"],
            ["roman_front_matter", "Pages liminaires en chiffres romains"],
            ["number_headings", "Numérotation des titres"],
            ["embed_remote_images", "Intégrer les images distantes (HTTP)"],
          ] as const
        ).map(([key, label]) => (
          <label key={key}>
            <input
              type="checkbox"
              checked={Boolean(options[key])}
              onChange={(event) => set(key, event.target.checked)}
            />
            <span>{label}</span>
          </label>
        ))}
      </fieldset>

      {preview ? (
        <div className="export-preview">
          <h3>Aperçu de l&apos;export</h3>
          <dl>
            <div>
              <dt>Style</dt>
              <dd>{preview.style_label}</dd>
            </div>
            <div>
              <dt>Sections</dt>
              <dd>{preview.section_count}</dd>
            </div>
            <div>
              <dt>Citations</dt>
              <dd>{preview.citation_count}</dd>
            </div>
            <div>
              <dt>Entrées de bibliographie</dt>
              <dd>{preview.bibliography_entries}</dd>
            </div>
            <div>
              <dt>Figures</dt>
              <dd>{preview.figure_count}</dd>
            </div>
            <div>
              <dt>Tableaux</dt>
              <dd>{preview.table_count}</dd>
            </div>
            <div>
              <dt>Annexes</dt>
              <dd>{preview.annex_count}</dd>
            </div>
            <div>
              <dt>Non citées</dt>
              <dd>{preview.uncited_count}</dd>
            </div>
          </dl>
          {preview.warnings.length > 0 ? (
            <ul className="export-warnings">
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
      {notice ? <p className="export-notice">{notice}</p> : null}

      {history.length > 0 ? (
        <div className="export-history">
          <h3>Derniers exports</h3>
          <ul>
            {history.slice(0, 5).map((record) => (
              <li key={record.id}>
                <strong>{record.file_name}</strong>
                <span>
                  {new Date(record.created_at).toLocaleString("fr-FR")} ·{" "}
                  {humanSize(record.size_bytes)}
                  {record.style_label ? ` · ${record.style_label}` : ""}
                </span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      <footer className="export-actions">
        <button className="button button--secondary button--small" type="button" onClick={onClose}>
          Annuler
        </button>
        <button
          className="button button--primary button--small"
          type="button"
          disabled={busy}
          onClick={() => void run()}
        >
          {busy ? "Génération…" : "Exporter"}
        </button>
      </footer>
    </div>
  );
}
