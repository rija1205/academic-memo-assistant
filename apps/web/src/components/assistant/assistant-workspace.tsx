"use client";

import {
  ApiError,
  askAssistant,
  createAssistantConversation,
  deleteAssistantConversation,
  getAssistantConfig,
  getAssistantConversation,
  listAssistantConversations,
  type AssistantAnswerStatus,
  type AssistantAskResponse,
  type AssistantCitation,
  type AssistantConfig,
  type AssistantConversationSummary,
  type AssistantMessage,
} from "@/lib/api";
import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";

function formatWhen(iso: string): string {
  const date = new Date(iso);
  const now = new Date();
  const sameDay = date.toDateString() === now.toDateString();
  return sameDay
    ? date.toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" })
    : date.toLocaleDateString("fr-FR", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
}

function groupConversations(
  items: AssistantConversationSummary[],
): { label: string; items: AssistantConversationSummary[] }[] {
  const today = new Date();
  const yesterday = new Date();
  yesterday.setDate(today.getDate() - 1);
  const buckets: Record<string, AssistantConversationSummary[]> = {
    "Aujourd'hui": [],
    Hier: [],
    "Plus ancien": [],
  };
  for (const item of items) {
    const date = new Date(item.updated_at);
    if (date.toDateString() === today.toDateString()) buckets["Aujourd'hui"].push(item);
    else if (date.toDateString() === yesterday.toDateString()) buckets.Hier.push(item);
    else buckets["Plus ancien"].push(item);
  }
  return Object.entries(buckets)
    .filter(([, values]) => values.length > 0)
    .map(([label, values]) => ({ label, items: values }));
}

export function AssistantWorkspace({ projectId }: { projectId: string }) {
  const [conversations, setConversations] = useState<AssistantConversationSummary[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [messages, setMessages] = useState<AssistantMessage[]>([]);
  const [question, setQuestion] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [config, setConfig] = useState<AssistantConfig | null>(null);
  const [showHistory, setShowHistory] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  const refreshConversations = useCallback(async () => {
    try {
      const list = await listAssistantConversations(projectId);
      setConversations(list.items);
      return list.items;
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Historique indisponible.");
      return [];
    }
  }, [projectId]);

  const openConversation = useCallback(
    async (conversationId: string) => {
      setError("");
      try {
        const detail = await getAssistantConversation(projectId, conversationId);
        setActiveId(detail.id);
        setMessages(detail.messages);
        setShowHistory(false);
      } catch (cause) {
        setError(cause instanceof ApiError ? cause.message : "Conversation indisponible.");
      }
    },
    [projectId],
  );

  useEffect(() => {
    void refreshConversations();
    void getAssistantConfig(projectId).then(setConfig).catch(() => undefined);
  }, [projectId, refreshConversations]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, pending]);

  async function startNewConversation() {
    setError("");
    try {
      const created = await createAssistantConversation(projectId);
      setActiveId(created.id);
      setMessages([]);
      setShowHistory(false);
      await refreshConversations();
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Création impossible.");
    }
  }

  async function send(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const text = question.trim();
    if (text.length < 2 || pending) return;
    setPending(true);
    setError("");
    setNotice("");
    setQuestion("");
    // Optimistic user bubble; replaced by the persisted message on reload.
    const optimistic: AssistantMessage = {
      id: `pending-${Date.now()}`,
      conversation_id: activeId ?? "",
      role: "user",
      content: text,
      status: "completed",
      sequence: messages.length + 1,
      llm_provider: null,
      llm_model: null,
      input_tokens: 0,
      output_tokens: 0,
      total_tokens: 0,
      estimated_cost_usd: null,
      cost_is_estimate: true,
      rag_duration_ms: 0,
      llm_duration_ms: 0,
      chunks_retrieved: 0,
      error_category: null,
      grounding_note: null,
      created_at: new Date().toISOString(),
      citations: [],
    };
    setMessages((current) => [...current, optimistic]);

    try {
      const response = await askAssistant(projectId, text, activeId ?? undefined);
      setActiveId(response.conversation_id);
      const assistantMessage = buildMessage(response);
      setMessages((current) => [
        ...current.filter((item) => item.id !== optimistic.id),
        assistantMessage,
      ]);
      if (response.status === "insufficient_sources") {
        setNotice(
          "Aucune source ne permet de répondre. Essayez une formulation plus large ou Launcher une recherche dans les sources.",
        );
      }
      if (response.rejected_citations.length > 0) {
        setNotice(
          `Référence${response.rejected_citations.length > 1 ? "s" : ""} non vérifiable${response.rejected_citations.length > 1 ? "s" : ""} retirée${response.rejected_citations.length > 1 ? "s" : ""} : ${response.rejected_citations.join(", ")}.`,
        );
      }
      await refreshConversations();
    } catch (cause) {
      setMessages((current) => current.filter((item) => item.id !== optimistic.id));
      setQuestion(text);
      if (cause instanceof ApiError && cause.status === 429) {
        setError("Limite d'utilisation atteinte. Patientez quelques instants avant de réessayer.");
      } else {
        setError(cause instanceof ApiError ? cause.message : "La question n'a pas pu être traitée.");
      }
    } finally {
      setPending(false);
    }
  }

  async function removeConversation(conversationId: string) {
    if (!window.confirm("Supprimer cette conversation ?")) return;
    try {
      await deleteAssistantConversation(projectId, conversationId);
      if (activeId === conversationId) {
        setActiveId(null);
        setMessages([]);
      }
      await refreshConversations();
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Suppression impossible.");
    }
  }

  return (
    <div className="assistant-layout">
      <aside className={`assistant-sidebar ${showHistory ? "open" : ""}`}>
        <button className="button button--primary button--full" type="button" onClick={() => void startNewConversation()}>
          + Nouvelle conversation
        </button>
        <nav className="assistant-history">
          {groupConversations(conversations).map((group) => (
            <div key={group.label} className="assistant-history-group">
              <h3>{group.label}</h3>
              {group.items.map((item) => (
                <div
                  key={item.id}
                  className={`assistant-history-item ${activeId === item.id ? "active" : ""}`}
                >
                  <button type="button" onClick={() => void openConversation(item.id)}>
                    {item.title}
                    <span>
                      {item.message_count} message(s) · {formatWhen(item.updated_at)}
                    </span>
                  </button>
                  <button
                    type="button"
                    className="assistant-history-delete"
                    aria-label={`Supprimer ${item.title}`}
                    onClick={() => void removeConversation(item.id)}
                  >
                    ×
                  </button>
                </div>
              ))}
            </div>
          ))}
          {conversations.length === 0 ? <p className="assistant-history-empty">Aucune conversation.</p> : null}
        </nav>
      </aside>

      <section className="assistant-main">
        <header className="assistant-header">
          <button
            className="button button--secondary button--small assistant-history-toggle"
            type="button"
            onClick={() => setShowHistory((value) => !value)}
          >
            Historique
          </button>
          <div>
            <h1>Assistant académique</h1>
            <p>
              Les réponses sont construites uniquement à partir des sources indexées de ce
              mémoire. Chaque affirmation vérifiable renvoie à un document et à une page.
            </p>
          </div>
          {config ? (
            <span className="assistant-model">
              {config.provider} · {config.model}
            </span>
          ) : null}
        </header>

        <div className="assistant-thread" aria-live="polite">
          {messages.length === 0 ? (
            <div className="assistant-empty">
              <span className="assistant-empty-icon">🎓</span>
              <h2>Posez votre première question</h2>
              <p>Exemples :</p>
              <ul>
                <li>Quels sont les principaux composants nutritionnels du grain de jacquier ?</li>
                <li>Que disent les sources sur la fermentation ?</li>
                <li>Quel est le taux de fibres mentionné dans mes documents ?</li>
              </ul>
              <p className="assistant-empty-note">
                Si vos sources ne permettent pas de répondre, l&apos;assistant vous le dira
                clairement plutôt que d&apos;inventer une réponse.
              </p>
            </div>
          ) : null}

          {messages.map((message) => (
            <Bubble key={message.id} message={message} />
          ))}
          {pending ? (
            <div className="assistant-bubble assistant-bubble--assistant assistant-bubble--pending">
              <span className="assistant-avatar">🤖</span>
              <div className="assistant-bubble-body">
                <span className="assistant-typing">Recherche dans vos sources…</span>
              </div>
            </div>
          ) : null}
          <div ref={bottomRef} />
        </div>

        {notice ? <p className="assistant-notice">{notice}</p> : null}
        {error ? <p className="form-error" role="alert">{error}</p> : null}

        <form className="assistant-composer" onSubmit={send}>
          <textarea
            aria-label="Poser une question à l'assistant"
            placeholder="Poser une question à vos sources…"
            rows={2}
            value={question}
            onChange={(event) => setQuestion(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                event.currentTarget.form?.requestSubmit();
              }
            }}
          />
          <button className="button button--primary" type="submit" disabled={pending || question.trim().length < 2}>
            {pending ? "…" : "Envoyer"}
          </button>
        </form>
        <p className="assistant-disclaimer">
          L&apos;assistant répond à partir de vos documents importés. Il ne génère pas de plan, de
          chapitre ni de bibliographie à ce stade.
        </p>
      </section>
    </div>
  );
}

function buildMessage(response: AssistantAskResponse): AssistantMessage {
  return {
    id: response.message_id,
    conversation_id: response.conversation_id,
    role: "assistant",
    content: response.user_message,
    status: response.status,
    sequence: 0,
    llm_provider: response.llm_provider,
    llm_model: response.llm_model,
    input_tokens: response.input_tokens,
    output_tokens: response.output_tokens,
    total_tokens: response.total_tokens,
    estimated_cost_usd: response.estimated_cost_usd,
    cost_is_estimate: response.cost_is_estimate,
    rag_duration_ms: response.rag_duration_ms,
    llm_duration_ms: response.llm_duration_ms,
    chunks_retrieved: response.chunks_retrieved,
    error_category: null,
    grounding_note: response.grounding_note,
    created_at: response.created_at,
    citations: response.citations,
  };
}

function Bubble({ message }: { message: AssistantMessage }) {
  const isUser = message.role === "user";
  const insufficient = message.status === "insufficient_sources" as AssistantAnswerStatus;
  return (
    <article className={`assistant-bubble ${isUser ? "assistant-bubble--user" : "assistant-bubble--assistant"}`}>
      <span className="assistant-avatar">{isUser ? "👤" : "🤖"}</span>
      <div className="assistant-bubble-body">
        <p className="assistant-bubble-text">{message.content}</p>
        {insufficient ? (
          <p className="assistant-insufficient">
            Aucun passage des sources indexées ne permet de traiter cette question.
          </p>
        ) : null}
        {message.grounding_note ? (
          <p className="assistant-grounding-note">⚠ {message.grounding_note}</p>
        ) : null}
        {!isUser && message.citations.length > 0 ? (
          <div className="assistant-citations">
            <h4>Sources utilisées</h4>
            {message.citations.map((citation) => (
              <CitationRow key={citation.citation_id} citation={citation} />
            ))}
          </div>
        ) : null}
        {!isUser && message.total_tokens > 0 ? (
          <p className="assistant-metrics">
            {message.chunks_retrieved} passage(s) · {message.total_tokens} tokens
            {message.estimated_cost_usd !== null
              ? ` · ~${message.estimated_cost_usd.toFixed(5)} $${message.cost_is_estimate ? " (estimation)" : ""}`
              : " · coût non disponible"}
            {" · "}
            RAG {message.rag_duration_ms} ms · modèle {message.llm_duration_ms} ms
          </p>
        ) : null}
        <span className="assistant-timestamp">{formatWhen(message.created_at)}</span>
      </div>
    </article>
  );
}

function CitationRow({ citation }: { citation: AssistantCitation }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="assistant-citation">
      <button type="button" className="assistant-citation-head" onClick={() => setOpen(!open)}>
        <span className="assistant-citation-index">[{citation.position}]</span>
        <span className="assistant-citation-title">
          {citation.source_title || citation.original_filename}
        </span>
        <span className="assistant-citation-page">p. {citation.page}</span>
      </button>
      {open ? (
        <div className="assistant-citation-detail">
          <p className="assistant-citation-quote">« {citation.quote} »</p>
          <p className="assistant-citation-meta">
            {citation.authors.join(", ") || "Auteur non renseigné"}
            {citation.publication_year ? ` (${citation.publication_year})` : ""} · score{" "}
            {citation.rag_score.toFixed(3)}
            {citation.provenance_id ? ` · provenance ${citation.provenance_id.slice(0, 8)}` : ""}
          </p>
          <Link
            className="button button--secondary button--small"
            href={citation.deep_link}
            target="_blank"
            rel="noreferrer"
          >
            Ouvrir le document à la page {citation.page}
          </Link>
        </div>
      ) : null}
    </div>
  );
}
