import { afterEach, describe, expect, it, vi } from "vitest";
import {
  discardWritingGeneration,
  generateWriting,
  getWritingCatalog,
  listWritingGenerations,
  type WritingCatalog,
  type WritingProposal,
} from "@/lib/api";

const CATALOG: WritingCatalog = {
  actions: [
    {
      action: "rephrase",
      label: "Reformuler",
      description: "Réécrit la sélection avec d'autres mots, sans changer le sens.",
      uses_sources: false,
      needs_selection: true,
      needs_full_section: false,
    },
    {
      action: "write_from_sources",
      label: "Rédiger depuis les sources",
      description: "Rédige un passage à partir des sources indexées du mémoire.",
      uses_sources: true,
      needs_selection: false,
      needs_full_section: false,
    },
  ],
  top_k: 8,
  max_selection_chars: 20000,
  max_section_chars: 60000,
};

const PROPOSAL: WritingProposal = {
  generation_id: "generation-1",
  action: "write_from_sources",
  status: "completed",
  proposed_text: "Le grain contient des fibres [1].",
  user_message: "Le grain contient des fibres [1].",
  citations: [
    {
      position: 1,
      citation_id: "SRC-001",
      chunk_id: "chunk-1",
      source_id: "source-1",
      source_file_id: "file-1",
      provenance_id: "prov-1",
      page: 12,
      quote: "Les fibres representent 20 pour cent du grain.",
      rag_score: 0.91,
      source_title: "Composition du jacquier",
      original_filename: "jacquier.pdf",
      deep_link: "/projects/project-1/sources?source=source-1&page=12",
    },
  ],
  rejected_citations: [],
  grounding_note: null,
  used_sources: true,
  chunks_retrieved: 3,
  reranked: true,
  llm_provider: "mock",
  llm_model: "gpt-4o-mini",
  input_tokens: 1200,
  output_tokens: 90,
  total_tokens: 1290,
  estimated_cost_usd: 0.0002,
  cost_is_estimate: true,
  rag_duration_ms: 40,
  llm_duration_ms: 800,
  error_category: null,
  created_at: "2026-09-29T10:00:00Z",
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

describe("writing assistant client", () => {
  it("exposes the action catalog", async () => {
    const fetchMock = mockFetch(CATALOG);
    const catalog = await getWritingCatalog("project-1");
    expect(fetchMock.mock.calls.at(-1)?.[0]).toBe(
      "/api/backend/api/projects/project-1/writing/actions",
    );
    expect(catalog.actions).toHaveLength(2);
    expect(catalog.actions[1].uses_sources).toBe(true);
  });

  it("sends the selection, the instruction and the section", async () => {
    const fetchMock = mockFetch(PROPOSAL);
    const result = await generateWriting("project-1", {
      action: "rephrase",
      instruction: "Garde le ton impersonnel",
      selection: "Le grain est riche.",
      section_text: "Section entiere",
      section_id: "section-1",
    });
    const call = fetchMock.mock.calls.at(-1) as [string, RequestInit];
    expect(call[0]).toBe("/api/backend/api/projects/project-1/writing/generate");
    expect(call[1].method).toBe("POST");
    expect(JSON.parse(String(call[1].body))).toMatchObject({
      action: "rephrase",
      instruction: "Garde le ton impersonnel",
      selection: "Le grain est riche.",
      section_text: "Section entiere",
      section_id: "section-1",
    });
    expect(result.citations[0].page).toBe(12);
  });

  it("reports insufficient sources without a fabricated text", async () => {
    mockFetch({
      ...PROPOSAL,
      status: "insufficient_sources",
      proposed_text: "",
      user_message: "Les sources indexees de ce memoire ne permettent pas de traiter cette demande.",
      citations: [],
      chunks_retrieved: 0,
      total_tokens: 0,
    });
    const result = await generateWriting("project-1", { action: "write_from_sources" });
    expect(result.status).toBe("insufficient_sources");
    expect(result.proposed_text).toBe("");
    expect(result.citations).toHaveLength(0);
  });

  it("surfaces rejected citations", async () => {
    mockFetch({ ...PROPOSAL, rejected_citations: ["SRC-OTHER-PROJECT"] });
    const result = await generateWriting("project-1", { action: "verify_claims" });
    expect(result.rejected_citations).toEqual(["SRC-OTHER-PROJECT"]);
  });

  it("lists the generation history for a section", async () => {
    const fetchMock = mockFetch({ items: [], total: 0 });
    const list = await listWritingGenerations("project-1", "section-1");
    expect(list.total).toBe(0);
    expect(fetchMock.mock.calls.at(-1)?.[0]).toBe(
      "/api/backend/api/projects/project-1/writing/generations?section_id=section-1",
    );
  });

  it("discards a proposal", async () => {
    const fetchMock = mockFetch({ ...PROPOSAL, id: PROPOSAL.generation_id, status: "discarded" });
    const result = await discardWritingGeneration("project-1", "generation-1");
    const call = fetchMock.mock.calls.at(-1) as [string, RequestInit];
    expect(call[0]).toBe(
      "/api/backend/api/projects/project-1/writing/generations/generation-1/discard",
    );
    expect(call[1].method).toBe("POST");
    expect(result.status).toBe("discarded");
  });
});
