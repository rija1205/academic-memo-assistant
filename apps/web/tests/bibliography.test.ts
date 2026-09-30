import { afterEach, describe, expect, it, vi } from "vitest";
import {
  createBibliographyReference,
  deleteBibliographyReference,
  exportBibliographyUrl,
  getBibliographyDuplicates,
  getBibliographyStats,
  importBibliographyFile,
  listBibliography,
  mergeBibliographyReference,
  searchBibliography,
  type BibliographyList,
  type BibliographyReference,
  type BibliographyStats,
} from "@/lib/api";

const REFERENCE: BibliographyReference = {
  id: "ref-1",
  project_id: "project-1",
  citation_key: "dupont2024",
  reference_type: "article",
  entry_type: "article",
  title: "Composition du grain de jacquier",
  subtitle: null,
  authors: [{ position: 1, given_name: "Jean", family_name: "Dupont", orcid: null }],
  publication_year: 2024,
  publication_month: null,
  publication_day: null,
  doi: "10.1234/example",
  doi_original: "https://doi.org/10.1234/example",
  url: "https://revue.ag/2024",
  accessed_at: null,
  journal: "Revue Agro",
  volume: "10",
  issue: "2",
  pages: "10-20",
  publisher: null,
  publisher_place: null,
  edition: null,
  isbn: null,
  issn: "1234-5678",
  abstract: null,
  keywords: ["jacquier"],
  language: "fr",
  notes: null,
  extra_fields: {},
  source_id: "source-1",
  source_title: "Article jacquier",
  tags: ["nutrition"],
  has_source: true,
  created_at: "2026-09-30T10:00:00Z",
  updated_at: "2026-09-30T10:00:00Z",
  missing_fields: ["publisher", "abstract"],
};

const LIST: BibliographyList = {
  items: [REFERENCE],
  total: 1,
  limit: 100,
  offset: 0,
};

const STATS: BibliographyStats = {
  total: 127,
  by_type: { article: 84, book: 15 },
  with_doi: 92,
  with_source: 78,
  with_url: 100,
  with_abstract: 60,
  by_year: { "2024": 20 },
};

function mockFetch(payload: unknown, status = 200) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, _init?: RequestInit) => {
    const url = String(input);
    // A 204 must be built with a null body, exactly like a real server response.
    if (status === 204) return new Response(null, { status });
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

describe("bibliography client", () => {
  it("lists references with filters", async () => {
    const fetchMock = mockFetch(LIST);
    await listBibliography("project-1", { reference_type: "article", year: 2024, has_doi: true });
    expect(fetchMock.mock.calls.at(-1)?.[0]).toBe(
      "/api/backend/api/projects/project-1/bibliography?reference_type=article&year=2024&has_doi=true",
    );
  });

  it("searches without involving the RAG or an LLM", async () => {
    const fetchMock = mockFetch(LIST);
    const result = await searchBibliography("project-1", "jacquier");
    expect(fetchMock.mock.calls.at(-1)?.[0]).toContain("bibliography?q=jacquier");
    expect(result.items[0].citation_key).toBe("dupont2024");
  });

  it("returns statistics computed by the API", async () => {
    mockFetch(STATS);
    const stats = await getBibliographyStats("project-1");
    expect(stats.total).toBe(127);
    expect(stats.by_type.article).toBe(84);
    expect(stats.with_doi).toBe(92);
    expect(stats.with_source).toBe(78);
  });

  it("creates a reference", async () => {
    const fetchMock = mockFetch(REFERENCE, 201);
    await createBibliographyReference("project-1", {
      reference_type: "article",
      title: "Composition du grain de jacquier",
    });
    const call = fetchMock.mock.calls.at(-1) as [string, RequestInit];
    expect(call[1].method).toBe("POST");
    expect(JSON.parse(String(call[1].body))).toMatchObject({
      reference_type: "article",
      title: "Composition du grain de jacquier",
    });
  });

  it("deletes a reference", async () => {
    const fetchMock = mockFetch({}, 204);
    await deleteBibliographyReference("project-1", "ref-1");
    const call = fetchMock.mock.calls.at(-1) as [string, RequestInit];
    expect(call[1].method).toBe("DELETE");
  });

  it("reports duplicates at three levels", async () => {
    mockFetch({
      has_duplicates: true,
      exact: [
        {
          reference_id: "ref-2",
          citation_key: "dupont2024b",
          title: "Même DOI",
          level: "exact",
          reason: "DOI identique (10.1234/example)",
          title_similarity: 0,
          shared_authors: [],
        },
      ],
      strong: [],
      possible: [
        {
          reference_id: "ref-3",
          citation_key: "dupont2024c",
          title: "Titre proche",
          level: "possible",
          reason: "Titre similaire (91%) et auteur commun : dupont",
          title_similarity: 0.91,
          shared_authors: ["dupont"],
        },
      ],
    });
    const report = await getBibliographyDuplicates("project-1", "ref-1");
    expect(report.has_duplicates).toBe(true);
    expect(report.exact[0].level).toBe("exact");
    expect(report.possible[0].shared_authors).toEqual(["dupont"]);
  });

  it("merges a duplicate into the kept reference", async () => {
    const fetchMock = mockFetch(REFERENCE);
    await mergeBibliographyReference("project-1", "ref-2", "ref-1");
    const call = fetchMock.mock.calls.at(-1) as [string, RequestInit];
    expect(call[0]).toBe("/api/backend/api/projects/project-1/bibliography/ref-2/merge");
    expect(JSON.parse(String(call[1].body))).toEqual({ keep_reference_id: "ref-1" });
  });

  it("builds export URLs for the whole library and for a selection", () => {
    expect(exportBibliographyUrl("project-1", "bibtex")).toBe(
      "/api/backend/api/projects/project-1/bibliography/export/bibtex",
    );
    expect(exportBibliographyUrl("project-1", "ris", ["a", "b"])).toBe(
      "/api/backend/api/projects/project-1/bibliography/export/ris?reference_ids=a,b",
    );
  });

  it("imports a BibTeX file and reports duplicates", async () => {
    const responseBody = {
      imported: 3,
      skipped: 0,
      duplicates: 1,
      errors: [{ message: "Entrée x ignorée", citation_key: "x" }],
      references: [REFERENCE],
    };
    const fetchMock = mockFetch(responseBody);
    const file = new File(["@article{a, title={T}}"], "library.bib", {
      type: "text/plain",
    });
    const result = await importBibliographyFile("project-1", "bibtex", file);
    const call = fetchMock.mock.calls.at(-1) as [string, RequestInit];
    expect(call[0]).toBe("/api/backend/api/projects/project-1/bibliography/import/bibtex");
    expect(result.imported).toBe(3);
    expect(result.duplicates).toBe(1);
    expect(result.errors[0].citation_key).toBe("x");
  });
});
