import { afterEach, describe, expect, it, vi } from "vitest";
import {
  getRagStats,
  listRagDocuments,
  ragSearch,
  reindexProjectRag,
  type RagSearchResponse,
} from "@/lib/api";

const EMPTY_SEARCH: RagSearchResponse = {
  query: "jacquier",
  strategy: "hybrid",
  fusion_method: "rrf",
  reranker: "none",
  top_k: 10,
  total_candidates: 3,
  duration_ms: 12,
  vector_hits: 3,
  lexical_hits: 2,
  results: [],
};

afterEach(() => {
  vi.unstubAllGlobals();
});

/**
 * The client first calls the CSRF endpoint, then the endpoint under test. Each fetch must
 * therefore receive its own fresh Response, routed by URL.
 */
function mockFetch(payload: unknown, status = 200) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, _init?: RequestInit) => {
    const url = String(input);
    const body = url.includes("/auth/csrf") ? { csrf_token: "test-token" } : payload;
    return new Response(JSON.stringify(body), { status });
  });
  vi.stubGlobal("fetch", fetchMock);
  // readCookie() reads document.cookie as a string, not a getter.
  vi.stubGlobal("document", { cookie: "ama_csrf=test-token" });
  return fetchMock;
}

describe("RAG client", () => {
  it("posts the question with the selected strategy", async () => {
    const fetchMock = mockFetch(EMPTY_SEARCH);
    await ragSearch("project-1", {
      query: "composants du jacquier",
      top_k: 5,
      strategy: "hybrid",
      filters: { publication_types: ["article"] },
    });
    const call = fetchMock.mock.calls.at(-1) as [string, RequestInit];
    expect(call[0]).toBe("/api/backend/api/projects/project-1/rag/search");
    expect(call[1].method).toBe("POST");
    expect(JSON.parse(String(call[1].body))).toMatchObject({
      query: "composants du jacquier",
      top_k: 5,
      strategy: "hybrid",
    });
  });

  it("exposes the index statistics", async () => {
    const fetchMock = mockFetch({
      documents_total: 3,
      documents_indexed: 2,
      documents_pending: 1,
      chunks_total: 48,
      tokens_total: 1200,
      estimated_cost_usd: 0.02,
      embedding_provider: "mock",
      embedding_model: "mock-hash-1536",
      embedding_dimension: 1536,
      embedding_version: "v1",
      chunking_version: "v1",
      chunk_max_tokens: 900,
      chunk_overlap_tokens: 120,
      search_strategy: "hybrid",
      fusion_method: "rrf",
      reranker: "none",
    });
    const stats = await getRagStats("project-1");
    expect(fetchMock.mock.calls[0][0]).toBe("/api/backend/api/projects/project-1/rag/stats");
    expect(stats.chunks_total).toBe(48);
    expect(stats.embedding_dimension).toBe(1536);
  });

  it("lists the indexed documents", async () => {
    mockFetch({ items: [], total: 0 });
    const documents = await listRagDocuments("project-1");
    expect(documents.total).toBe(0);
  });

  it("triggers a project reindex as a mutation", async () => {
    const fetchMock = mockFetch({ message: "3 source(s) programmée(s).", queued: true });
    await reindexProjectRag("project-1");
    const call = fetchMock.mock.calls.at(-1) as [string, RequestInit];
    expect(call[0]).toBe("/api/backend/api/projects/project-1/rag/reindex");
    expect(call[1].method).toBe("POST");
  });
});
