"use client";

import {
  ApiError,
  deindexSourceInRag,
  getRagStats,
  indexSourceInRag,
  listRagDocuments,
  listRagQueryHistory,
  ragSearch,
  reindexProjectRag,
  reindexSourceInRag,
  type RagDocument,
  type RagQueryHistoryEntry,
  type RagSearchResponse,
  type RagSearchResult,
  type RagStats,
  type RagStrategy,
} from "@/lib/api";
import { useCallback, useEffect, useState } from "react";

const STRATEGIES: { value: RagStrategy; label: string; hint: string }[] = [
  { value: "hybrid", label: "Hybride", hint: "Vectoriel + lexique, fusion RRF" },
  { value: "semantic", label: "Sémantique", hint: "Embeddings uniquement" },
  { value: "lexical", label: "Lexical", hint: "Recherche par mots, sans embedding" },
];

function ragStatusLabel(status: RagDocument["status"]): string {
  if (status === "indexed") return "Indexée";
  if (status === "pending") return "En attente";
  if (status === "chunking") return "Découpage";
  if (status === "embedding") return "Embeddings";
  return "Échec";
}

function scorePercent(value: number, strategy: RagStrategy): string {
  if (strategy === "semantic" || strategy === "hybrid") {
    const normalized = Math.max(0, Math.min(1, value));
    return `${(normalized * 100).toFixed(0)} %`;
  }
  return value.toFixed(3);
}

export function RagWorkspace({ projectId }: { projectId: string }) {
  const [query, setQuery] = useState("");
  const [strategy, setStrategy] = useState<RagStrategy>("hybrid");
  const [topK, setTopK] = useState(10);
  const [searching, setSearching] = useState(false);
  const [response, setResponse] = useState<RagSearchResponse | null>(null);
  const [error, setError] = useState("");
  const [documents, setDocuments] = useState<RagDocument[]>([]);
  const [stats, setStats] = useState<RagStats | null>(null);
  const [history, setHistory] = useState<RagQueryHistoryEntry[]>([]);
  const [busySource, setBusySource] = useState<string | null>(null);

  const loadIndex = useCallback(async () => {
    try {
      const [documentList, indexStats] = await Promise.all([
        listRagDocuments(projectId),
        getRagStats(projectId),
      ]);
      setDocuments(documentList.items);
      setStats(indexStats);
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Index RAG indisponible.");
    }
  }, [projectId]);

  const loadHistory = useCallback(async () => {
    try {
      const entries = await listRagQueryHistory(projectId, 10);
      setHistory(entries.items);
    } catch {
      // The history panel is optional and must never break the search interface.
    }
  }, [projectId]);

  useEffect(() => {
    void loadIndex();
    void loadHistory();
  }, [loadIndex, loadHistory]);

  async function runSearch(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (query.trim().length < 2) {
      setError("Saisissez au moins deux caractères.");
      return;
    }
    setSearching(true);
    setError("");
    try {
      const result = await ragSearch(projectId, {
        query: query.trim(),
        top_k: topK,
        strategy,
        filters: {},
      });
      setResponse(result);
      void loadHistory();
    } catch (cause) {
      setResponse(null);
      setError(cause instanceof ApiError ? cause.message : "Recherche impossible.");
    } finally {
      setSearching(false);
    }
  }

  async function act(sourceId: string, action: (id: string) => Promise<unknown>) {
    setBusySource(sourceId);
    setError("");
    try {
      await action(sourceId);
      await loadIndex();
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Action impossible.");
    } finally {
      setBusySource(null);
    }
  }

  return (
    <div className="rag-workspace">
      <header className="rag-header">
        <div>
          <p className="eyebrow">RAG académique</p>
          <h1>Recherche dans mes sources</h1>
          <p>
            Le moteur retrouve les passages pertinents dans les documents importés et affiche
            leur provenance exacte. Aucune réponse n&apos;est générée à ce stade.
          </p>
        </div>
        {stats ? (
          <dl className="rag-stats">
            <div><dt>Documents indexés</dt><dd>{stats.documents_indexed}/{stats.documents_total}</dd></div>
            <div><dt>Passages</dt><dd>{stats.chunks_total}</dd></div>
            <div><dt>Tokens envoyés</dt><dd>{stats.tokens_total.toLocaleString("fr-FR")}</dd></div>
            <div>
              <dt>Coût estimé</dt>
              <dd>{stats.estimated_cost_usd > 0 ? `${stats.estimated_cost_usd.toFixed(4)} $` : "Non disponible"}</dd>
            </div>
          </dl>
        ) : null}
      </header>

      <form className="rag-search-form" onSubmit={runSearch}>
        <input
          aria-label="Question posée aux sources"
          placeholder="Quels sont les principaux composants nutritionnels du grain de jacquier ?"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
        />
        <select
          aria-label="Stratégie de recherche"
          value={strategy}
          onChange={(event) => setStrategy(event.target.value as RagStrategy)}
        >
          {STRATEGIES.map((item) => (
            <option key={item.value} value={item.value}>{item.label}</option>
          ))}
        </select>
        <select
          aria-label="Nombre de résultats"
          value={topK}
          onChange={(event) => setTopK(Number(event.target.value))}
        >
          {[5, 10, 20, 30].map((value) => (
            <option key={value} value={value}>{value} résultats</option>
          ))}
        </select>
        <button className="button button--primary" type="submit" disabled={searching}>
          {searching ? "Recherche…" : "Rechercher"}
        </button>
      </form>
      <p className="rag-strategy-hint">
        {STRATEGIES.find((item) => item.value === strategy)?.hint}
        {stats
          ? ` · Embeddings ${stats.embedding_model} (${stats.embedding_dimension} dimensions) · fusion ${stats.fusion_method.toUpperCase()}`
          : ""}
      </p>

      {error ? <p className="form-error" role="alert">{error}</p> : null}

      {response ? (
        <section className="rag-results" aria-live="polite">
          <div className="rag-results-summary">
            <strong>{response.results.length} passage(s)</strong>
            <span>
              {response.strategy}
              {response.fusion_method ? ` · fusion ${response.fusion_method}` : ""}
              {" · "}
              {response.duration_ms} ms
              {" · "}
              vectoriel {response.vector_hits} / lexical {response.lexical_hits}
            </span>
          </div>
          {response.results.length === 0 ? (
            <p className="empty-panel">
              Aucun passage ne correspond. Reformulez la question ou changez de stratégie.
            </p>
          ) : (
            <ol className="rag-result-list">
              {response.results.map((result) => (
                <ResultCard key={result.chunk_id} result={result} strategy={strategy} />
              ))}
            </ol>
          )}
        </section>
      ) : (
        <p className="empty-panel">
          Posez une question pour retrouver les passages pertinents et leur provenance.
        </p>
      )}

      <section className="rag-index-panel">
        <div className="panel-heading">
          <h2>État de l&apos;index</h2>
          <button
            className="button button--secondary button--small"
            type="button"
            onClick={() => void act("project", () => reindexProjectRag(projectId))}
          >
            Réindexer le projet
          </button>
        </div>
        {documents.length === 0 ? (
          <p className="empty-panel">
            Aucune source indexée. L&apos;indexation est automatique après le traitement d&apos;une
            source ; utilisez « Réindexer le projet » si nécessaire.
          </p>
        ) : (
          <table className="rag-index-table">
            <thead>
              <tr>
                <th>Source</th>
                <th>Statut</th>
                <th>Passages</th>
                <th>Signature d&apos;index</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {documents.map((document) => (
                <tr key={document.id}>
                  <td>
                    <strong>{document.source_title || document.original_filename}</strong>
                    {document.needs_reindex ? (
                      <small className="rag-warning">
                        Index obsolète : rebuild requis après un changement de configuration.
                      </small>
                    ) : null}
                    {document.error_message ? (
                      <small className="form-error">{document.error_message}</small>
                    ) : null}
                  </td>
                  <td>
                    <span className={`rag-status rag-status--${document.status}`}>
                      {ragStatusLabel(document.status)}
                    </span>
                  </td>
                  <td>{document.chunk_count}</td>
                  <td>
                    <code className="rag-signature">
                      {document.embedding_model} · {document.embedding_dimension}d ·{" "}
                      {document.embedding_version}/{document.chunking_version}
                    </code>
                  </td>
                  <td className="rag-actions">
                    <button
                      type="button"
                      disabled={busySource === document.source_id}
                      onClick={() =>
                        void act(document.source_id, (id) => reindexSourceInRag(projectId, id))
                      }
                    >
                      Réindexer
                    </button>
                    <button
                      type="button"
                      disabled={busySource === document.source_id}
                      onClick={() =>
                        void act(document.source_id, (id) => indexSourceInRag(projectId, id, true))
                      }
                    >
                      Forcer
                    </button>
                    <button
                      type="button"
                      disabled={busySource === document.source_id}
                      onClick={() =>
                        void act(document.source_id, (id) => deindexSourceInRag(projectId, id))
                      }
                    >
                      Désindexer
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      {history.length > 0 ? (
        <section className="rag-history">
          <h2>Recherches récentes</h2>
          <ul>
            {history.map((entry) => (
              <li key={entry.id}>
                <button type="button" onClick={() => setQuery(entry.query)}>{entry.query}</button>
                <span>
                  {entry.strategy} · {entry.result_count} résultat(s) · {entry.duration_ms} ms
                </span>
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </div>
  );
}

function ResultCard({ result, strategy }: { result: RagSearchResult; strategy: RagStrategy }) {
  const [open, setOpen] = useState(false);
  const heading = result.provenance.heading_path.length > 0
    ? result.provenance.heading_path.join(" › ")
    : null;
  return (
    <li className="rag-result">
      <div className="rag-result-head">
        <div>
          <strong>{result.source.title || result.source.original_filename}</strong>
          <span>
            {result.source.authors.join(", ") || "Auteur non renseigné"}
            {result.source.year ? ` (${result.source.year})` : ""} · page {result.page}
          </span>
        </div>
        <span className="rag-score" title="Score de pertinence">
          Score : {scorePercent(result.score, strategy)}
        </span>
      </div>
      {heading ? <p className="rag-heading-path">{heading}</p> : null}
      <p className="rag-snippet">{result.text}</p>
      <div className="rag-result-meta">
        <code title="Provenance complète">
          {result.source.original_filename} · p. {result.page} · bloc{" "}
          {result.provenance.block_start}-{result.provenance.block_end} ·{" "}
          {result.provenance.provenance_id.slice(0, 8)}
        </code>
        <button className="button button--secondary button--small" type="button" onClick={() => setOpen(!open)}>
          {open ? "Masquer" : "Provenance"}
        </button>
        <a
          className="button button--secondary button--small"
          href={`/projects/${result.provenance.project_id}/sources?source=${result.source.id}&page=${result.page}`}
        >
          Voir la source
        </a>
      </div>
      {open ? (
        <dl className="rag-provenance">
          <div><dt>Projet</dt><dd>{result.provenance.project_id}</dd></div>
          <div><dt>Source</dt><dd>{result.provenance.source_id}</dd></div>
          <div><dt>Fichier</dt><dd>{result.provenance.source_file_id ?? "Non renseigné"}</dd></div>
          <div><dt>Page</dt><dd>{result.provenance.page_number}</dd></div>
          <div><dt>Bloc</dt><dd>{result.provenance.block_start} → {result.provenance.block_end}</dd></div>
          <div><dt>Provenance</dt><dd>{result.provenance.provenance_id}</dd></div>
          <div><dt>Chunk</dt><dd>{result.provenance.chunk_id}</dd></div>
          <div><dt>Position</dt><dd>{result.provenance.character_start} → {result.provenance.character_end}</dd></div>
          <div><dt>Citation</dt><dd>{result.citation_marker}</dd></div>
          <div>
            <dt>Scores</dt>
            <dd>
              vectoriel {result.vector_score?.toFixed(4) ?? "—"} · lexical{" "}
              {result.lexical_score?.toFixed(4) ?? "—"} · rerank{" "}
              {result.rerank_score?.toFixed(4) ?? "—"}
            </dd>
          </div>
        </dl>
      ) : null}
    </li>
  );
}
