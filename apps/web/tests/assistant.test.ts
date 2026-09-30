import { afterEach, describe, expect, it, vi } from "vitest";
import {
  askAssistant,
  createAssistantConversation,
  deleteAssistantConversation,
  getAssistantConfig,
  getAssistantConversation,
  listAssistantConversations,
  type AssistantAskResponse,
  type AssistantConfig,
} from "@/lib/api";

const ANSWER: AssistantAskResponse = {
  status: "completed",
  message_id: "message-1",
  conversation_id: "conversation-1",
  question: "Quels sont les composants du jacquier ?",
  answer: "Le grain contient des glucides, des proteines et des lipides. [1]",
  user_message: "Le grain contient des glucides, des proteines et des lipides. [1]",
  citations: [
    {
      position: 1,
      citation_id: "SRC-001",
      chunk_id: "chunk-1",
      source_id: "source-1",
      source_file_id: "file-1",
      provenance_id: "prov-1",
      page: 12,
      quote: "Le grain contient des proteines vegetales.",
      rag_score: 0.91,
      source_title: "Composition du jacquier",
      original_filename: "jacquier.pdf",
      authors: ["A. Nkolo"],
      publication_year: 2024,
      deep_link: "/projects/project-1/sources?source=source-1&page=12",
    },
  ],
  rejected_citations: [],
  grounding_note: null,
  chunks_retrieved: 3,
  reranked: true,
  llm_provider: "mock",
  llm_model: "gpt-4o-mini",
  input_tokens: 1200,
  output_tokens: 180,
  total_tokens: 1380,
  estimated_cost_usd: 0.0002,
  cost_is_estimate: true,
  rag_duration_ms: 42,
  llm_duration_ms: 900,
  created_at: "2026-09-28T10:00:00Z",
};

const CONFIG: AssistantConfig = {
  provider: "openai",
  model: "gpt-4o-mini",
  temperature: 0,
  max_output_tokens: 900,
  max_input_tokens: 12000,
  max_history_messages: 10,
  top_k: 8,
  min_context_score: 0,
  rate_limit_enabled: true,
};

function mockFetch(payload: unknown, status = 200) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, _init?: RequestInit) => {
    const url = String(input);
    const body = url.includes("/auth/csrf") ? { csrf_token: "token" } : payload;
    return new Response(JSON.stringify(body), { status });
  });
  vi.stubGlobal("fetch", fetchMock);
  vi.stubGlobal("document", { cookie: "ama_csrf=test-token" });
  return fetchMock;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("assistant client", () => {
  it("sends a question and returns grounded citations", async () => {
    const fetchMock = mockFetch(ANSWER);
    const response = await askAssistant("project-1", "Quels sont les composants du jacquier ?");
    const call = fetchMock.mock.calls.at(-1) as [string, RequestInit];

    expect(call[0]).toBe("/api/backend/api/projects/project-1/assistant/ask");
    expect(call[1].method).toBe("POST");
    expect(JSON.parse(String(call[1].body))).toMatchObject({
      question: "Quels sont les composants du jacquier ?",
      conversation_id: null,
    });
    expect(response.citations[0].page).toBe(12);
    expect(response.citations[0].provenance_id).toBe("prov-1");
  });

  it("reports insufficient sources without a fabricated answer", async () => {
    mockFetch({
      ...ANSWER,
      status: "insufficient_sources",
      answer: null,
      citations: [],
      chunks_retrieved: 0,
      total_tokens: 0,
    });
    const response = await askAssistant("project-1", "Question hors sujet ?");
    expect(response.status).toBe("insufficient_sources");
    expect(response.answer).toBeNull();
    expect(response.citations).toHaveLength(0);
  });

  it("surfaces rejected citations so the UI can warn", async () => {
    mockFetch({ ...ANSWER, rejected_citations: ["SRC-OTHER-PROJECT"] });
    const response = await askAssistant("project-1", "Question ?");
    expect(response.rejected_citations).toEqual(["SRC-OTHER-PROJECT"]);
  });

  it("creates, reads and deletes a conversation", async () => {
    const createMock = mockFetch({
      id: "conversation-1",
      project_id: "project-1",
      title: "Nouvelle conversation",
      message_count: 0,
      created_at: "2026-09-28T10:00:00Z",
      updated_at: "2026-09-28T10:00:00Z",
      summary: null,
      messages: [],
    });
    const created = await createAssistantConversation("project-1");
    expect(created.id).toBe("conversation-1");
    expect(createMock.mock.calls.at(-1)?.[0]).toBe(
      "/api/backend/api/projects/project-1/assistant/conversations",
    );

    const readMock = mockFetch({ ...created, messages: [] });
    await getAssistantConversation("project-1", "conversation-1");
    expect(readMock.mock.calls.at(-1)?.[0]).toBe(
      "/api/backend/api/projects/project-1/assistant/conversations/conversation-1",
    );

    const deleteMock = mockFetch({ message: "Conversation supprimée.", conversation_id: "conversation-1" });
    await deleteAssistantConversation("project-1", "conversation-1");
    const deleteCall = deleteMock.mock.calls.at(-1) as [string, RequestInit];
    expect(deleteCall[1].method).toBe("DELETE");
  });

  it("lists conversations", async () => {
    const fetchMock = mockFetch({ items: [], total: 0 });
    const list = await listAssistantConversations("project-1");
    expect(list.total).toBe(0);
    expect(fetchMock.mock.calls.at(-1)?.[0]).toBe(
      "/api/backend/api/projects/project-1/assistant/conversations",
    );
  });

  it("exposes the assistant configuration without any secret", async () => {
    mockFetch(CONFIG);
    const config = await getAssistantConfig("project-1");
    expect(config.provider).toBe("openai");
    expect(JSON.stringify(config)).not.toContain("api_key");
  });
});
