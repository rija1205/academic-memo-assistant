import { afterEach, describe, expect, it, vi } from "vitest";
import {
  CITATION_NODE_NAME,
  CitationNode,
  buildCitationContent,
  collectCitations,
  isLegacyCitation,
  type CitationNodeAttrs,
} from "@/components/citations/citation-node";
import {
  BIBLIOGRAPHY_BLOCK_NAME,
  BibliographyBlock,
  buildBibliographyContent,
} from "@/components/citations/bibliography-block";
import {
  deleteCitation,
  detachCitationReference,
  getCitationStyles,
  getRenderedBibliography,
  getRenderedCitations,
  listCitations,
  patchCitation,
  previewCitation,
  reconcileCitations,
  refreshBibliography,
  upsertCitation,
  type Citation,
  type RenderedBibliography,
} from "@/lib/api";

function mockFetch(payload: unknown, status = 200) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, _init?: RequestInit) => {
    const url = String(input);
    if (status === 204) return new Response(null, { status });
    const body = url.includes("/auth/csrf") ? { csrf_token: "token" } : payload;
    return new Response(JSON.stringify(body), { status });
  });
  vi.stubGlobal("fetch", fetchMock);
  vi.stubGlobal("document", { cookie: "ama_csrf=test-token" });
  return fetchMock;
}

const REFERENCE_ID = "11111111-1111-4111-8111-111111111111";
const OTHER_REFERENCE_ID = "22222222-2222-4222-8222-222222222222";

const CITATION: Citation = {
  id: "citation-1",
  project_id: "project-1",
  section_id: "section-1",
  node_id: "cit-1",
  citation_key: "dupont2024-cit-1",
  prefix: null,
  suffix: null,
  locator_type: null,
  locator_value: null,
  mode: "parenthetical",
  position_in_section: 0,
  items: [
    {
      reference_id: REFERENCE_ID,
      citation_key: "dupont2024",
      title: "Composition du grain",
      publication_year: 2024,
      author_labels: ["Jean Dupont"],
      position: 1,
      is_available: true,
      number: null,
      locator_type: "page",
      locator_value: "25",
      prefix: null,
      suffix: null,
    },
  ],
  rendered_text: "(Dupont, 2024, p. 25)",
  warnings: [],
  is_orphaned: false,
  is_complete: true,
  is_stale_snapshot: false,
  snapshot_text: "(Dupont, 2024, p. 25)",
  created_at: "2026-10-07T10:00:00Z",
  updated_at: "2026-10-07T10:00:00Z",
};

const BIBLIOGRAPHY: RenderedBibliography = {
  style: "apa7",
  style_label: "APA 7",
  entries: [
    {
      reference_id: REFERENCE_ID,
      number: null,
      text: "Dupont, J. (2024). Composition du grain.",
      warnings: [],
      citation_keys: ["dupont2024-cit-1"],
      is_complete: true,
    },
  ],
  cited_count: 1,
  uncited_count: 2,
  uncited: [
    {
      reference_id: OTHER_REFERENCE_ID,
      citation_key: "martin2023",
      title: "Propriétés fonctionnelles",
      publication_year: 2023,
      reference_type: "article",
    },
  ],
  orphaned_citations: [],
  incomplete_count: 0,
  is_truncated: false,
};

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("citation node", () => {
  it("is an inline atom named citation", () => {
    expect(CITATION_NODE_NAME).toBe("citation");
    expect(CitationNode.config.name).toBe("citation");
    expect(CitationNode.config.inline).toBe(true);
    expect(CitationNode.config.atom).toBe(true);
  });

  it("carries the identity and not the text as truth", () => {
    const content = buildCitationContent({
      citationId: "cit-1",
      referenceIds: [REFERENCE_ID],
      text: "(Dupont, 2024)",
    });
    expect(content.type).toBe("citation");
    const attrs = content.attrs as Record<string, unknown>;
    expect(attrs.citationId).toBe("cit-1");
    expect(attrs.referenceIds).toEqual([REFERENCE_ID]);
    // The rendered string is a convenience for display, never the identifier.
    expect(attrs.text).toBe("(Dupont, 2024)");
  });

  it("serialises to JSON and back without losing anything", () => {
    const content = buildCitationContent({
      citationId: "cit-1",
      referenceIds: [REFERENCE_ID, OTHER_REFERENCE_ID],
      text: "(Dupont, 2024; Martin, 2023)",
      mode: "narrative",
      locatorType: "pages",
      locatorValue: "25-28",
      prefix: "Voir ",
      suffix: ", p. 25",
      warnings: ["Année non renseignée."],
    });
    const roundTripped = JSON.parse(JSON.stringify(content));
    expect(roundTripped).toEqual(content);
    const [node] = collectCitations({ type: "doc", content: [roundTripped] });
    expect(node.citationId).toBe("cit-1");
    expect(node.referenceIds).toEqual([REFERENCE_ID, OTHER_REFERENCE_ID]);
    expect(node.mode).toBe("narrative");
    expect(node.locatorType).toBe("pages");
    expect(node.locatorValue).toBe("25-28");
    expect(node.prefix).toBe("Voir ");
    expect(node.suffix).toBe(", p. 25");
    expect(node.warnings).toEqual(["Année non renseignée."]);
  });

  it("collects several references in one node, in order", () => {
    const document = {
      type: "doc",
      content: [
        {
          type: "paragraph",
          content: [
            buildCitationContent({
              citationId: "cit-1",
              referenceIds: [OTHER_REFERENCE_ID, REFERENCE_ID],
              text: "(Martin, 2023; Dupont, 2024)",
            }),
          ],
        },
      ],
    };
    const [node] = collectCitations(document);
    expect(node.referenceIds).toEqual([OTHER_REFERENCE_ID, REFERENCE_ID]);
  });

  it("collects citations in document order across nesting", () => {
    const document = {
      type: "doc",
      content: [
        {
          type: "paragraph",
          content: [buildCitationContent({ citationId: "n1", referenceIds: ["a"], text: "a" })],
        },
        {
          type: "blockquote",
          content: [
            {
              type: "paragraph",
              content: [
                buildCitationContent({ citationId: "n2", referenceIds: ["b"], text: "b" }),
              ],
            },
          ],
        },
      ],
    };
    expect(collectCitations(document).map((node) => node.citationId)).toEqual(["n1", "n2"]);
  });

  it("finds a citation inside a table cell", () => {
    const document = {
      type: "doc",
      content: [
        {
          type: "table",
          content: [
            {
              type: "tableRow",
              content: [
                {
                  type: "tableCell",
                  content: [
                    {
                      type: "paragraph",
                      content: [
                        buildCitationContent({ citationId: "deep", referenceIds: ["x"], text: "x" }),
                      ],
                    },
                  ],
                },
              ],
            },
          ],
        },
      ],
    };
    expect(collectCitations(document).map((node) => node.citationId)).toEqual(["deep"]);
  });

  it("returns nothing for a document without citation", () => {
    expect(collectCitations({ type: "doc", content: [{ type: "paragraph" }] })).toEqual([]);
  });

  it("tolerates a malformed document", () => {
    expect(collectCitations(null)).toEqual([]);
    expect(collectCitations({})).toEqual([]);
    expect(collectCitations({ content: "nope" })).toEqual([]);
  });

  it("renders the orphan state distinctly", () => {
    const content = buildCitationContent({
      citationId: "cit-9",
      referenceIds: [REFERENCE_ID],
      text: "[Citation invalide : référence introuvable]",
      isOrphaned: true,
    });
    expect((content.attrs as Record<string, unknown>).isOrphaned).toBe(true);
  });

  it("keeps a stage 3 free-text placeholder readable and detectable", () => {
    const legacy: CitationNodeAttrs = {
      citationId: "",
      referenceIds: [],
      mode: "parenthetical",
      locatorType: null,
      locatorValue: null,
      prefix: null,
      suffix: null,
      text: "",
      isOrphaned: false,
      warnings: [],
      legacyValue: "Auteur2025",
    };
    // A free-text key is not a reference identifier, so it is never treated as a citation.
    expect(isLegacyCitation(legacy)).toBe(true);
    expect(isLegacyCitation({ ...legacy, citationId: "cit-1" })).toBe(false);
  });

  it("declares every attribute the server sends back", () => {
    // buildCitationContent is the single place that writes the attributes, so checking its
    // output covers the whole contract the API relies on.
    const attrs = buildCitationContent({
      citationId: "cit-1",
      referenceIds: [REFERENCE_ID],
      text: "(Dupont, 2024)",
    }).attrs as Record<string, unknown>;
    for (const name of [
      "citationId",
      "referenceIds",
      "mode",
      "locatorType",
      "locatorValue",
      "prefix",
      "suffix",
      "text",
      "isOrphaned",
      "warnings",
      "legacyValue",
    ]) {
      expect(attrs).toHaveProperty(name);
    }
  });
});

describe("bibliography block", () => {
  it("is an atom that the author cannot type into", () => {
    expect(BIBLIOGRAPHY_BLOCK_NAME).toBe("bibliographyBlock");
    expect(BibliographyBlock.config.atom).toBe(true);
    expect(BibliographyBlock.config.draggable).toBe(false);
  });

  it("holds the generated lines and their counters", () => {
    const content = buildBibliographyContent({
      blockId: "bib-1",
      style: "apa7",
      lines: ["Dupont, J. (2024). Composition du grain."],
      entryCount: 1,
      uncitedCount: 2,
      orphanCount: 0,
      generatedAt: "2026-10-07T10:00:00Z",
    });
    expect(content.type).toBe("bibliographyBlock");
    const attrs = content.attrs as Record<string, unknown>;
    expect(attrs.entryCount).toBe(1);
    expect(attrs.uncitedCount).toBe(2);
    expect(attrs.orphanCount).toBe(0);
    expect(attrs.lines).toEqual(["Dupont, J. (2024). Composition du grain."]);
  });

  it("survives a JSON round trip so an export keeps the identifiers", () => {
    const content = buildBibliographyContent({
      blockId: "bib-1",
      style: "vancouver",
      lines: ["1. Dupont. Article A. 2024."],
      entryCount: 1,
      uncitedCount: 0,
      orphanCount: 0,
      generatedAt: "2026-10-07T10:00:00Z",
    });
    expect(JSON.parse(JSON.stringify(content))).toEqual(content);
  });
});

describe("citation client", () => {
  it("lists the citations of a section", async () => {
    const fetchMock = mockFetch({ items: [CITATION], total: 1 });
    const result = await listCitations("project-1", "section-1");
    expect(fetchMock.mock.calls.at(-1)?.[0]).toBe(
      "/api/backend/api/projects/project-1/citations?section_id=section-1",
    );
    expect(result.items[0].rendered_text).toBe("(Dupont, 2024, p. 25)");
  });

  it("asks the server for the rendered text rather than formatting it locally", async () => {
    const fetchMock = mockFetch({
      section_id: "section-1",
      style: "apa7",
      style_label: "APA 7",
      citations: [
        {
          node_id: "cit-1",
          citation_id: "citation-1",
          text: "(Dupont, 2024)",
          is_orphaned: false,
          warnings: [],
          reference_ids: [REFERENCE_ID],
        },
      ],
      orphaned: [],
    });
    const result = await getRenderedCitations("project-1", "section-1");
    expect(fetchMock.mock.calls.at(-1)?.[0]).toContain("/citations/rendered");
    expect(result.citations[0].text).toBe("(Dupont, 2024)");
    expect(result.style_label).toBe("APA 7");
  });

  it("previews an unstored citation through the same endpoint", async () => {
    const fetchMock = mockFetch({
      style: "apa7",
      style_label: "APA 7",
      citation: "(Dupont, 2024, p. 25)",
      bibliography_entry: "Dupont, J. (2024). Composition du grain.",
      warnings: [],
      uses_style_engine: true,
    });
    const preview = await previewCitation("project-1", {
      items: [{ reference_id: REFERENCE_ID, locator_type: "page", locator_value: "25" }],
    });
    const call = fetchMock.mock.calls.at(-1) as [string, RequestInit];
    expect(call[0]).toBe("/api/backend/api/projects/project-1/citations/preview");
    expect(call[1].method).toBe("POST");
    expect(JSON.parse(String(call[1].body)).items[0].locator_value).toBe("25");
    expect(preview.citation).toBe("(Dupont, 2024, p. 25)");
    expect(preview.uses_style_engine).toBe(true);
  });

  it("creates a citation for a node", async () => {
    const fetchMock = mockFetch(CITATION, 201);
    const created = await upsertCitation("project-1", {
      section_id: "section-1",
      node_id: "cit-1",
      items: [{ reference_id: REFERENCE_ID, locator_type: "page", locator_value: "25" }],
      mode: "parenthetical",
    });
    const call = fetchMock.mock.calls.at(-1) as [string, RequestInit];
    expect(call[0]).toBe("/api/backend/api/projects/project-1/citations");
    expect(JSON.parse(String(call[1].body)).node_id).toBe("cit-1");
    expect(created.items[0].reference_id).toBe(REFERENCE_ID);
  });

  it("updates a citation with a PATCH", async () => {
    const fetchMock = mockFetch(CITATION);
    await patchCitation("project-1", "citation-1", { suffix: ", p. 25" });
    const call = fetchMock.mock.calls.at(-1) as [string, RequestInit];
    expect(call[1].method).toBe("PATCH");
    expect(JSON.parse(String(call[1].body))).toEqual({ suffix: ", p. 25" });
  });

  it("detaches one reference to repair an orphan", async () => {
    const fetchMock = mockFetch(CITATION);
    await detachCitationReference("project-1", "citation-1", REFERENCE_ID);
    expect(fetchMock.mock.calls.at(-1)?.[0]).toContain(
      "/citations/citation-1/detach-reference?reference_id=",
    );
  });

  it("deletes a citation without touching the reference", async () => {
    const fetchMock = mockFetch({}, 204);
    await deleteCitation("project-1", "citation-1");
    const call = fetchMock.mock.calls.at(-1) as [string, RequestInit];
    expect(call[0]).toBe("/api/backend/api/projects/project-1/citations/citation-1");
    expect(call[1].method).toBe("DELETE");
  });

  it("reconciles a saved document and reports what needs repair", async () => {
    const fetchMock = mockFetch({
      section_id: "section-1",
      style: "apa7",
      citations: [],
      unregistered_node_ids: ["legacy-1"],
      stale_citation_ids: ["citation-9"],
      orphaned_node_ids: ["cit-7"],
      synced: 2,
    });
    const check = await reconcileCitations("project-1", "section-1", {
      type: "doc",
      content: [],
    });
    expect(fetchMock.mock.calls.at(-1)?.[0]).toContain("section_id=section-1");
    expect(check.synced).toBe(2);
    expect(check.unregistered_node_ids).toEqual(["legacy-1"]);
    expect(check.orphaned_node_ids).toEqual(["cit-7"]);
  });

  it("reports uncited references and orphans separately", async () => {
    mockFetch(BIBLIOGRAPHY);
    const rendered = await getRenderedBibliography("project-1");
    expect(rendered.cited_count).toBe(1);
    expect(rendered.uncited_count).toBe(2);
    expect(rendered.uncited[0].citation_key).toBe("martin2023");
    expect(rendered.orphaned_citations).toEqual([]);
  });

  it("refreshes the bibliography with a POST", async () => {
    const fetchMock = mockFetch(BIBLIOGRAPHY);
    await refreshBibliography("project-1");
    const call = fetchMock.mock.calls.at(-1) as [string, RequestInit];
    expect(call[0]).toBe("/api/backend/api/projects/project-1/bibliography/refresh");
    expect(call[1].method).toBe("POST");
  });

  it("lists the style catalogue instead of hard-coding it", async () => {
    mockFetch([
      { name: "apa7", label: "APA 7", uses_numbers: false, date_missing: "s.d." },
      { name: "harvard", label: "Harvard", uses_numbers: false, date_missing: "n.d." },
      { name: "vancouver", label: "Vancouver", uses_numbers: true, date_missing: "" },
      { name: "iso690", label: "ISO 690 (numérique)", uses_numbers: true, date_missing: "n.d." },
    ]);
    const styles = await getCitationStyles("project-1");
    expect(styles.map((style) => style.name)).toEqual([
      "apa7",
      "harvard",
      "vancouver",
      "iso690",
    ]);
  });
});
