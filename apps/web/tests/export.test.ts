import { afterEach, describe, expect, it, vi } from "vitest";
import {
  downloadExport,
  getExportCatalogue,
  listExports,
  previewExport,
  type ExportCatalogue,
  type ExportList,
  type ExportPreview,
  type ExportRecord,
} from "@/lib/api";

const PREVIEW: ExportPreview = {
  format: "pdf",
  style: "apa7",
  style_label: "APA 7",
  project_title: "Memoire de test",
  section_count: 3,
  section_titles: ["Introduction", "Resultats", "Annexe A"],
  figure_count: 2,
  table_count: 1,
  citation_count: 5,
  bibliography_entries: 4,
  uncited_count: 7,
  orphan_count: 1,
  annex_count: 1,
  warnings: ["1 citation(s) invalide(s) : reference introuvable."],
  has_cover: true,
  has_toc: true,
};

const RECORD: ExportRecord = {
  id: "export-1",
  project_id: "project-1",
  format: "pdf",
  file_name: "Memoire_de_test_Rakoto_2026.pdf",
  size_bytes: 254_000,
  style: "apa7",
  style_label: "APA 7",
  section_count: 3,
  figure_count: 2,
  table_count: 1,
  citation_count: 5,
  uncited_count: 7,
  orphan_count: 1,
  warnings: [],
  duration_ms: 420,
  created_at: "2026-10-14T09:00:00Z",
};

const CATALOGUE: ExportCatalogue = {
  formats: [
    { format: "pdf", label: "PDF", extension: "pdf", media_type: "application/pdf" },
    {
      format: "docx",
      label: "Word (DOCX)",
      extension: "docx",
      media_type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    },
  ],
  page_sizes: ["a4", "letter"],
  fonts: [{ name: "times", label: "Times New Roman" }],
  defaults: { page_size: "a4", font_size: 12, limits: { max_sections: 2000 } },
};

function jsonMock(payload: unknown, status = 200) {
  // The second parameter is declared so vitest records the whole call, options included.
  const mock = vi.fn(async (input: RequestInfo | URL, _init?: RequestInit) => {
    const url = String(input);
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

describe("export client", () => {
  it("reads the catalogue from the server instead of hard-coding formats", async () => {
    const mock = jsonMock(CATALOGUE);
    const catalogue = await getExportCatalogue("project-1");
    expect(mock.mock.calls.at(-1)?.[0]).toBe("/api/backend/api/projects/project-1/exports/formats");
    expect(catalogue.formats.map((item) => item.format)).toEqual(["pdf", "docx"]);
  });

  it("previews an export through the server, which runs the citation engine", async () => {
    const mock = jsonMock(PREVIEW);
    const preview = await previewExport("project-1", "pdf", { font_size: 11 });
    const call = mock.mock.calls.at(-1) as [string, RequestInit];
    expect(call[0]).toBe("/api/backend/api/projects/project-1/exports/preview");
    expect(JSON.parse(String(call[1].body))).toEqual({
      format: "pdf",
      options: { font_size: 11 },
    });
    expect(preview.style_label).toBe("APA 7");
    expect(preview.citation_count).toBe(5);
    // The warnings the file will really contain are visible before generating it.
    expect(preview.warnings).toHaveLength(1);
  });

  it("lists the export history", async () => {
    const mock = jsonMock({ items: [RECORD], total: 1 } satisfies ExportList);
    const history = await listExports("project-1");
    expect(mock.mock.calls.at(-1)?.[0]).toBe("/api/backend/api/projects/project-1/exports?limit=10");
    expect(history.items[0].file_name).toBe("Memoire_de_test_Rakoto_2026.pdf");
  });

  it("downloads the file the server produced", async () => {
    const payload = new Uint8Array([0x25, 0x50, 0x44, 0x46]);
    const mock = vi.fn(async (input: RequestInfo | URL, _init?: RequestInit) => {
      const url = String(input);
      if (url.includes("/auth/csrf")) {
        return new Response(JSON.stringify({ csrf_token: "token" }), { status: 200 });
      }
      return new Response(payload, {
        status: 200,
        headers: {
          "Content-Type": "application/pdf",
          "Content-Disposition": 'attachment; filename="Memoire.pdf"',
        },
      });
    });
    vi.stubGlobal("fetch", mock);
    vi.stubGlobal("document", { cookie: "ama_csrf=test-token" });
    const createObjectURL = vi.fn(() => "blob:memoire");
    const revokeObjectURL = vi.fn();
    vi.stubGlobal("URL", { ...URL, createObjectURL, revokeObjectURL });
    const click = vi.fn();
    vi.stubGlobal("document", {
      cookie: "ama_csrf=test-token",
      createElement: () => ({ click, remove: vi.fn(), style: {} }),
      body: { appendChild: vi.fn() },
    });

    const result = await downloadExport("project-1", "pdf", { include_cover: false });
    const call = mock.mock.calls.at(-1) as [string, RequestInit];
    expect(call[0]).toBe("/api/backend/api/projects/project-1/exports/pdf");
    expect(call[1].method).toBe("POST");
    expect(JSON.parse(String(call[1].body))).toEqual({ include_cover: false });
    expect(result.fileName).toBe("Memoire.pdf");
    expect(result.size).toBe(4);
    expect(click).toHaveBeenCalled();
    expect(revokeObjectURL).toHaveBeenCalled();
  });

  it("surfaces the server message when the export fails", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.includes("/auth/csrf")) {
          return new Response(JSON.stringify({ csrf_token: "token" }), { status: 200 });
        }
        return new Response(JSON.stringify({ detail: "Document trop volumineux." }), {
          status: 422,
        });
      }),
    );
    vi.stubGlobal("document", { cookie: "ama_csrf=test-token" });
    await expect(downloadExport("project-1", "pdf")).rejects.toThrow(
      "Document trop volumineux.",
    );
  });
});
