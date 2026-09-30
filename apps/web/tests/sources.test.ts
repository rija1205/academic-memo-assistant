import { afterEach, describe, expect, it, vi } from "vitest";
import { listSources, searchSources } from "@/lib/api";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("source library client", () => {
  it("builds a filtered source-library request", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ items: [], total: 0, limit: 20, offset: 0 }), { status: 200 }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await listSources("project-1", { q: "article", status: "processed", limit: 20 });

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/backend/api/projects/project-1/sources?q=article&status=processed&limit=20",
      expect.objectContaining({ credentials: "include", cache: "no-store" }),
    );
  });

  it("uses the local extracted-text search endpoint", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ query: "data", results: [], total: 0 }), { status: 200 }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await searchSources("project-1", "data", 25);

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/backend/api/projects/project-1/sources/search?q=data&limit=25",
      expect.objectContaining({ credentials: "include", cache: "no-store" }),
    );
  });
});
