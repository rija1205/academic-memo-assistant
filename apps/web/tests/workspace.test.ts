import { afterEach, describe, expect, it, vi } from "vitest";
import { getCsrfToken, saveSectionContent } from "@/lib/api";
import { calculateProgress, moveOutlineNode } from "@/lib/workspace";
import type { OutlineNode } from "@/lib/api";

const node = (id: string, parent_id: string | null, position: number): OutlineNode => ({
  id,
  project_id: "project",
  parent_id,
  section_id: `section-${id}`,
  kind: parent_id ? "subsection" : "section",
  title: id,
  position,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("workspace helpers", () => {
  it("calculates progress from completed sections", () => {
    expect(calculateProgress(["complete", "complete", "in_progress", "empty"])).toBe(50);
    expect(calculateProgress([])).toBe(0);
  });

  it("creates a normalized move payload", () => {
    const nodes = [node("a", null, 0), node("b", null, 1), node("c", null, 2)];
    expect(moveOutlineNode(nodes, "c", null, 0)).toEqual([
      { node_id: "c", parent_id: null, position: 0 },
      { node_id: "a", parent_id: null, position: 1 },
      { node_id: "b", parent_id: null, position: 2 },
    ]);
  });

  it("sends versioned content through the autosave endpoint", async () => {
    const section = {
      id: "section-1",
      project_id: "project-1",
      outline_node_id: "node-1",
      title: "Introduction",
      content: { type: "doc", content: [{ type: "paragraph" }] },
      plain_text: "",
      status: "empty" as const,
      word_count: 0,
      version: 1,
      last_saved_by: null,
      created_at: "2026-01-01T00:00:00Z",
      updated_at: "2026-01-01T00:00:00Z",
    };
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ csrf_token: "csrf-token" }), { status: 200 }),
      )
      .mockResolvedValueOnce(new Response(JSON.stringify(section), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    await getCsrfToken(true);
    const saved = await saveSectionContent("project-1", "section-1", {
      content: section.content,
      plain_text: "",
      expected_version: 1,
    });

    expect(saved.version).toBe(1);
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "/api/backend/api/projects/project-1/sections/section-1/content",
      expect.objectContaining({ method: "PUT", credentials: "include" }),
    );
  });
});
