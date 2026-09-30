import type { OutlineNode, SectionStatus } from "@/lib/api";

export function calculateProgress(statuses: SectionStatus[]): number {
  if (!statuses.length) return 0;
  const completed = statuses.filter((status) => status === "complete").length;
  return Math.round((completed / statuses.length) * 1000) / 10;
}

export function outlineDepth(node: OutlineNode, nodes: OutlineNode[]): number {
  let depth = 0;
  let parentId = node.parent_id;
  const visited = new Set<string>();
  while (parentId && !visited.has(parentId)) {
    visited.add(parentId);
    depth += 1;
    parentId = nodes.find((candidate) => candidate.id === parentId)?.parent_id ?? null;
    if (depth > 2) break;
  }
  return Math.min(depth, 2);
}

export function sortOutline(nodes: OutlineNode[]): OutlineNode[] {
  return [...nodes].sort((left, right) => {
    const leftParent = left.parent_id ?? "";
    const rightParent = right.parent_id ?? "";
    if (leftParent !== rightParent) return leftParent.localeCompare(rightParent);
    if (left.position !== right.position) return left.position - right.position;
    return left.created_at.localeCompare(right.created_at);
  });
}

export function moveOutlineNode(
  nodes: OutlineNode[],
  nodeId: string,
  targetParentId: string | null,
  targetIndex: number,
): { node_id: string; parent_id: string | null; position: number }[] {
  const node = nodes.find((candidate) => candidate.id === nodeId);
  if (!node) throw new Error("Outline node not found.");
  const siblings = nodes
    .filter((candidate) => candidate.parent_id === targetParentId && candidate.id !== nodeId)
    .sort((left, right) => left.position - right.position);
  const index = Math.max(0, Math.min(targetIndex, siblings.length));
  siblings.splice(index, 0, node);
  return siblings.map((candidate, position) => ({
    node_id: candidate.id,
    parent_id: targetParentId,
    position,
  }));
}
