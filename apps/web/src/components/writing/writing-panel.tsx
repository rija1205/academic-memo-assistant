"use client";

import {
  ApiError,
  discardWritingGeneration,
  generateWriting,
  getWritingCatalog,
  listWritingGenerations,
  type WritingAction,
  type WritingActionMeta,
  type WritingCitation,
  type WritingGeneration,
  type WritingProposal,
} from "@/lib/api";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

export interface EditorSelection {
  from: number;
  to: number;
  text: string;
}

/**
 * Proposal panel for the academic writing assistant.
 *
 * The panel never writes to the editor by itself. It returns a proposal and the author
 * decides: insert, replace, copy, regenerate or discard.
 */
export function WritingPanel({
  projectId,
  sectionId,
  selection,
  sectionText,
  onInsert,
  onReplace,
  readOnly = false,
}: {
  projectId: string;
  sectionId: string;
  selection: EditorSelection;
  sectionText: string;
  onInsert: (text: string) => void;
  onReplace: (text: string) => void;
  readOnly?: boolean;
}) {
  const [catalog, setCatalog] = useState<WritingActionMeta[]>([]);
  const [action, setAction] = useState<WritingAction>("rephrase");
  const [instruction, setInstruction] = useState("");
  const [proposal, setProposal] = useState<WritingProposal | null>(null);
  const [history, setHistory] = useState<WritingGeneration[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [showHistory, setShowHistory] = useState(false);
  const [copied, setCopied] = useState(false);

  const loadHistory = useCallback(async () => {
    try {
      const list = await listWritingGenerations(projectId, sectionId);
      setHistory(list.items);
    } catch {
      // The history panel is optional and must never block writing.
    }
  }, [projectId, sectionId]);

  useEffect(() => {
    void getWritingCatalog(projectId)
      .then((value) => setCatalog(value.actions))
      .catch(() => setError("Catalogue d'actions indisponible."));
    void loadHistory();
  }, [loadHistory, projectId]);

  const current = catalog.find((item) => item.action === action);
  const selectionEmpty = selection.text.trim().length === 0;

  async function run(target: WritingAction = action) {
    if (busy || readOnly) return;
    setBusy(true);
    setError("");
    setCopied(false);
    try {
      const result = await generateWriting(projectId, {
        action: target,
        instruction,
        selection: selection.text,
        section_text: sectionText,
        previous_text: previousSentence(selection.text),
        section_id: sectionId,
      });
      setProposal(result);
      await loadHistory();
    } catch (cause) {
      setProposal(null);
      setError(
        cause instanceof ApiError
          ? cause.status === 429
            ? "Limite d'utilisation atteinte. Patientez quelques instants."
            : cause.message
          : "La génération a échoué.",
      );
    } finally {
      setBusy(false);
    }
  }

  async function copy() {
    if (!proposal) return;
    try {
      await navigator.clipboard.writeText(proposal.proposed_text);
      setCopied(true);
    } catch {
      setError("Copie impossible dans ce navigateur.");
    }
  }

  async function discard() {
    if (!proposal) return;
    setProposal(null);
    if (proposal.status === "completed") {
      await discardWritingGeneration(projectId, proposal.generation_id).catch(() => undefined);
      await loadHistory();
    }
  }

  if (readOnly) {
    return (
      <section className="writing-panel writing-panel--readonly">
        <p className="writing-readonly">L&apos;assistant de rédaction est réservé aux rôles éditeur et propriétaire.</p>
      </section>
    );
  }

  return (
    <section className="writing-panel" aria-label="Assistant de rédaction">
      <header className="writing-panel-head">
        <h2>Assistant de rédaction</h2>
        <button
          type="button"
          className="button button--secondary button--small"
          onClick={() => setShowHistory((value) => !value)}
        >
          Historique ({history.length})
        </button>
      </header>
      <p className="writing-selection-info">
        {selectionEmpty
          ? "Aucune sélection : l'action s'appuiera sur la section entière."
          : `Sélection : ${selection.text.length} caractères`}
      </p>

      <div className="writing-actions" role="group" aria-label="Actions de rédaction">
        {catalog.map((item) => (
          <button
            key={item.action}
            type="button"
            className={`writing-action ${action === item.action ? "active" : ""}`}
            title={item.description}
            onClick={() => setAction(item.action)}
          >
            {item.label}
            {item.uses_sources ? <span className="writing-action-flag" title="Utilise les sources">◈</span> : null}
          </button>
        ))}
      </div>
      {current ? <p className="writing-action-description">{current.description}</p> : null}

      <div className="writing-instruction">
        <input
          aria-label="Instruction de rédaction (facultative)"
          placeholder="Instruction (facultatif) : ex. « garde le ton impersonnel »"
          value={instruction}
          onChange={(event) => setInstruction(event.target.value)}
          maxLength={1000}
        />
        <button
          className="button button--primary button--small"
          type="button"
          onClick={() => void run()}
          disabled={busy || (current?.needs_selection ? selectionEmpty : false) || (current?.needs_full_section && !sectionText.trim())}
        >
          {busy ? "Génération…" : "Proposer"}
        </button>
      </div>

      {error ? <p className="form-error" role="alert">{error}</p> : null}

      {proposal ? (
        <ProposalCard
          proposal={proposal}
          busy={busy}
          copied={copied}
          canReplace={!selectionEmpty}
          onInsert={() => {
            onInsert(proposal.proposed_text);
            setProposal(null);
          }}
          onReplace={() => {
            onReplace(proposal.proposed_text);
            setProposal(null);
          }}
          onCopy={() => void copy()}
          onRegenerate={() => void run()}
          onDiscard={() => void discard()}
        />
      ) : null}

      {showHistory ? (
        <div className="writing-history">
          <h3>Générations précédentes</h3>
          {history.length === 0 ? <p>Aucune génération pour cette section.</p> : null}
          <ul>
            {history.map((item) => (
              <li key={item.id}>
                <button type="button" onClick={() => setProposal(fromHistory(item))}>
                  <strong>{item.action}</strong>
                  <span>
                    {item.status} · {item.total_tokens} tokens
                    {item.estimated_cost_usd !== null ? ` · ~${item.estimated_cost_usd.toFixed(5)} $` : ""}
                    {item.llm_model ? ` · ${item.llm_model}` : ""}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </section>
  );
}

function ProposalCard({
  proposal,
  busy,
  copied,
  canReplace,
  onInsert,
  onReplace,
  onCopy,
  onRegenerate,
  onDiscard,
}: {
  proposal: WritingProposal;
  busy: boolean;
  copied: boolean;
  canReplace: boolean;
  onInsert: () => void;
  onReplace: () => void;
  onCopy: () => void;
  onRegenerate: () => void;
  onDiscard: () => void;
}) {
  const insufficient = proposal.status === "insufficient_sources";
  return (
    <article className="writing-proposal">
      <header className="writing-proposal-head">
        <strong>Proposition du modèle</strong>
        <span>
          {proposal.llm_model ?? "modèle"} · {proposal.total_tokens} tokens
          {proposal.estimated_cost_usd !== null
            ? ` · ~${proposal.estimated_cost_usd.toFixed(5)} ${proposal.cost_is_estimate ? "$ (est.)" : "$"}`
            : ""}
        </span>
      </header>
      {insufficient ? (
        <p className="writing-insufficient">{proposal.user_message}</p>
      ) : (
        <p className="writing-proposal-text">{proposal.proposed_text}</p>
      )}
      {proposal.grounding_note ? (
        <p className="writing-grounding-note">⚠ {proposal.grounding_note}</p>
      ) : null}
      {proposal.rejected_citations.length > 0 ? (
        <p className="writing-grounding-note">
          ⚠ Référence{proposal.rejected_citations.length > 1 ? "s" : ""} non vérifiable
          {proposal.rejected_citations.length > 1 ? "s" : ""} retirée
          {proposal.rejected_citations.length > 1 ? "s" : ""} : {proposal.rejected_citations.join(", ")}.
        </p>
      ) : null}
      {proposal.citations.length > 0 ? (
        <div className="writing-citations">
          <h4>Sources ({proposal.chunks_retrieved} passage(s))</h4>
          {proposal.citations.map((citation) => (
            <CitationRow key={citation.citation_id} citation={citation} />
          ))}
        </div>
      ) : null}
      {!insufficient ? (
        <div className="writing-proposal-actions">
          <button type="button" className="button button--primary button--small" onClick={onInsert} disabled={busy}>
            Insérer
          </button>
          <button type="button" className="button button--secondary button--small" onClick={onReplace} disabled={busy || !canReplace}>
            Remplacer
          </button>
          <button type="button" className="button button--secondary button--small" onClick={onCopy}>
            {copied ? "Copié ✓" : "Copier"}
          </button>
          <button type="button" className="button button--secondary button--small" onClick={onRegenerate} disabled={busy}>
            Régénérer
          </button>
          <button type="button" className="button button--danger button--small" onClick={onDiscard} disabled={busy}>
            Annuler
          </button>
        </div>
      ) : null}
    </article>
  );
}

function CitationRow({ citation }: { citation: WritingCitation }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="writing-citation">
      <button type="button" className="writing-citation-head" onClick={() => setOpen(!open)}>
        <span className="writing-citation-index">[{citation.position}]</span>
        <span>{citation.source_title || citation.original_filename}</span>
        <span className="writing-citation-page">p. {citation.page}</span>
      </button>
      {open ? (
        <div className="writing-citation-detail">
          <p className="writing-citation-quote">« {citation.quote} »</p>
          {citation.provenance_id ? (
            <p className="writing-citation-meta">
              score {citation.rag_score.toFixed(3)} · provenance {citation.provenance_id.slice(0, 8)}
            </p>
          ) : null}
          <Link className="button button--secondary button--small" href={citation.deep_link} target="_blank" rel="noreferrer">
            Ouvrir à la page {citation.page}
          </Link>
        </div>
      ) : null}
    </div>
  );
}

function fromHistory(item: WritingGeneration): WritingProposal {
  return {
    generation_id: item.id,
    action: item.action,
    status: item.status,
    proposed_text: item.proposed_text,
    user_message: item.status === "insufficient_sources" ? item.proposed_text : item.proposed_text,
    citations: item.citations,
    rejected_citations: [],
    grounding_note: item.grounding_note,
    used_sources: item.used_sources,
    chunks_retrieved: item.chunks_retrieved,
    reranked: false,
    llm_provider: item.llm_provider,
    llm_model: item.llm_model,
    input_tokens: item.input_tokens,
    output_tokens: item.output_tokens,
    total_tokens: item.total_tokens,
    estimated_cost_usd: item.estimated_cost_usd,
    cost_is_estimate: item.cost_is_estimate,
    rag_duration_ms: 0,
    llm_duration_ms: 0,
    error_category: item.error_category,
    created_at: item.created_at,
  };
}

/** Previous sentence, used by the transition action. */
function previousSentence(selection: string): string {
  return selection.split(/(?<=[.!?])\s+/).slice(-2, -1)[0]?.slice(-400) ?? "";
}
