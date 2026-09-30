import { afterEach, describe, expect, it, vi } from "vitest";
import {
  deleteAuditTrace,
  getAuditReport,
  listAuditTraces,
  runAudit,
  type AuditReport,
  type AuditTraceList,
} from "@/lib/api";

const REPORT: AuditReport = {
  project_id: "project-1",
  project_title: "Memoire de test",
  generated_at: "2026-10-21T09:00:00Z",
  readiness: {
    level: "corrections_requises",
    label: "2 point(s) bloquant(s) a traiter",
    detail: "Corrigez les points bloquants avant de deposer le memoire.",
  },
  summary: {
    blockers: 2,
    warnings: 5,
    info: 7,
    checks_run: 23,
    checks_inconclusive: 1,
    labels: { blocker: "Bloquant", warning: "A verifier", info: "Information" },
  },
  findings: [
    {
      code: "citations.orphelines",
      severity: "blocker",
      severity_label: "Bloquant",
      title: "Citation orpheline",
      detail: "La reference citee a ete supprimee.",
      location_kind: "citation",
      location_ref: "citation-1",
      location_label: "Introduction",
      remedy: "Rattacher une reference existante ou retirer la citation.",
      count: 1,
      meta: {},
    },
    {
      code: "bibliographie.non_citees",
      severity: "info",
      severity_label: "Information",
      title: "Reference jamais citee",
      detail: "Elle ne figurera pas dans la bibliographie finale.",
      location_kind: "reference",
      location_ref: "ref-1",
      location_label: "dupont2024",
      remedy: "La citer si elle est utilisee.",
      count: 1,
      meta: {},
    },
  ],
  findings_by_code: { "citations.orphelines": 1, "bibliographie.non_citees": 1 },
  checks: [
    { code: "citations.orphelines", finding_count: 1, skipped_reason: null },
    {
      code: "structure.sections_attendues",
      finding_count: 0,
      skipped_reason: "Le projet ne declare pas de plan type.",
    },
  ],
  statistics: {
    project_id: "project-1",
    title: "Memoire de test",
    section_count: 4,
    chapter_count: 4,
    subsection_count: 0,
    empty_section_count: 1,
    completed_section_count: 3,
    word_count: 12400,
    character_count: 74000,
    read_minutes: 62,
    longest_section: "Resultats",
    longest_section_words: 5200,
    average_section_words: 3100,
    citation_count: 18,
    distinct_cited_references: 14,
    orphan_citation_count: 1,
    pending_citation_count: 0,
    narrative_citation_count: 2,
    reference_count: 22,
    uncited_reference_count: 7,
    references_with_doi: 16,
    references_with_url: 4,
    reference_type_counts: { article: 15, book: 4, thesis: 2, report: 1 },
    reference_year_span: [2015, 2026],
    most_cited_references: [
      { reference_id: "r1", citation_key: "dupont2024", title: "Composition", count: 3 },
    ],
    citation_density: 14.5,
    bibliography_style: "apa7",
    dangling_citation_references: 1,
    source_count: 9,
    indexed_source_count: 8,
    source_page_count: 210,
    source_block_count: 640,
    figure_count: 6,
    table_count: 3,
    equation_count: 2,
    sections: [
      {
        section_id: "s1",
        title: "Introduction",
        level: 1,
        word_count: 2000,
        citation_count: 5,
        figure_count: 1,
        table_count: 0,
        status: "complete",
        citation_density: 25,
        read_minutes: 10,
      },
    ],
  },
  observations: [
    { code: "volume.density_faible", label: "Densite de citation faible", detail: "14.5 / 1000 mots." },
  ],
  defence_checklist: [
    { priority: 1, category: "Bloquant", question: "Citation orpheline - Introduction", evidence: "Rattacher." },
    { priority: 2, category: "Source insuffisante", question: "Controle non concluant", evidence: "Pas de plan type." },
  ],
  disclaimer: "Cet audit est deterministe : il ne reecrit rien.",
};

function jsonMock(payload: unknown, status = 200) {
  const mock = vi.fn(async (input: RequestInfo | URL, _init?: RequestInit) => {
    const url = String(input);
    // A 204 carries no body, exactly like a real server response.
    if (status === 204) return new Response(null, { status });
    const body = url.includes("/auth/csrf") ? { csrf_token: "token" } : payload;
    return new Response(JSON.stringify(body), { status });
  });
  vi.stubGlobal("fetch", mock);
  vi.stubGlobal("document", { cookie: "ama_csrf=test-token" });
  return mock;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("audit client", () => {
  it("reads the report", async () => {
    const mock = jsonMock(REPORT);
    const report = await getAuditReport("project-1");
    expect(mock.mock.calls.at(-1)?.[0]).toBe("/api/backend/api/projects/project-1/audit");
    expect(report.summary.blockers).toBe(2);
    expect(report.summary.checks_run).toBe(23);
  });

  it("exposes the three severity levels in a stable order", async () => {
    jsonMock(REPORT);
    const report = await getAuditReport("project-1");
    const order = report.findings.map((finding) => finding.severity);
    expect(order.indexOf("blocker")).toBeLessThan(order.indexOf("info"));
  });

  it("surfaces an inconclusive check instead of hiding it", async () => {
    jsonMock(REPORT);
    const report = await getAuditReport("project-1");
    const inconclusive = report.checks.filter((check) => check.skipped_reason);
    expect(inconclusive).toHaveLength(1);
    expect(report.summary.checks_inconclusive).toBe(1);
  });

  it("never proposes an automatic repair in a remedy", async () => {
    jsonMock(REPORT);
    const report = await getAuditReport("project-1");
    for (const finding of report.findings) {
      const remedy = (finding.remedy ?? "").toLowerCase();
      expect(remedy).not.toContain("automatiquement");
    }
  });

  it("runs an audit without storing a trace by default", async () => {
    const mock = jsonMock({ report: REPORT, trace_id: null, duration_ms: 180 });
    const result = await runAudit("project-1");
    const call = mock.mock.calls.at(-1) as [string, RequestInit];
    expect(call[0]).toBe("/api/backend/api/projects/project-1/audit/run");
    expect(call[1].method).toBe("POST");
    expect(JSON.parse(String(call[1].body))).toEqual({ store_trace: false });
    expect(result.trace_id).toBeNull();
    expect(result.duration_ms).toBe(180);
  });

  it("stores a trace on request", async () => {
    const mock = jsonMock({ report: REPORT, trace_id: "trace-1", duration_ms: 200 });
    const result = await runAudit("project-1", true);
    const call = mock.mock.calls.at(-1) as [string, RequestInit];
    expect(JSON.parse(String(call[1].body))).toEqual({ store_trace: true });
    expect(result.trace_id).toBe("trace-1");
  });

  it("lists the audit history with the blocker trend", async () => {
    const history: AuditTraceList = {
      items: [
        {
          id: "t2",
          project_id: "project-1",
          readiness: "corrections_requises",
          blocker_count: 2,
          warning_count: 5,
          info_count: 7,
          checks_run: 23,
          checks_inconclusive: 1,
          word_count: 12400,
          citation_count: 18,
          reference_count: 22,
          findings: [],
          duration_ms: 180,
          created_at: "2026-10-21T09:00:00Z",
        },
      ],
      total: 2,
      blocker_trend: 3,
    };
    const mock = jsonMock(history);
    const result = await listAuditTraces("project-1");
    expect(mock.mock.calls.at(-1)?.[0]).toBe("/api/backend/api/projects/project-1/audit/traces");
    expect(result.blocker_trend).toBe(3);
  });

  it("deletes a trace", async () => {
    const mock = jsonMock({}, 204);
    await deleteAuditTrace("project-1", "t1");
    const call = mock.mock.calls.at(-1) as [string, RequestInit];
    expect(call[0]).toBe("/api/backend/api/projects/project-1/audit/traces/t1");
    expect(call[1].method).toBe("DELETE");
  });
});
