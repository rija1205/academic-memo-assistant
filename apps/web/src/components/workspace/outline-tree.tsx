"use client";

import type { OutlineNode } from "@/lib/api";
import { outlineDepth, sortOutline } from "@/lib/workspace";

export function OutlineTree({
  nodes,
  selectedId,
  onSelect,
  onAdd,
  onRename,
  onDuplicate,
  onDelete,
  onMove,
  canEdit = true,
}: {
  nodes: OutlineNode[];
  selectedId: string | null;
  onSelect: (node: OutlineNode) => void;
  onAdd: (parentId: string | null, kind: "section" | "subsection") => void;
  onRename: (node: OutlineNode) => void;
  onDuplicate: (node: OutlineNode) => void;
  onDelete: (node: OutlineNode) => void;
  onMove: (node: OutlineNode, targetParentId: string | null, targetIndex: number) => void;
  canEdit?: boolean;
}) {
  const ordered = sortOutline(nodes);
  return (
    <aside className="outline-panel" aria-label="Structure du mémoire">
      <div className="panel-heading">
        <div><p className="eyebrow">Plan</p><h2>Structure</h2></div>
        {canEdit ? <button className="icon-button" type="button" onClick={() => onAdd(null, "section")} aria-label="Ajouter une section">+</button> : null}
      </div>
      <p className="panel-hint">{canEdit ? "Glissez une ligne ou utilisez les actions pour réorganiser." : "Consultation seule."}</p>
      <div className="outline-list">
        {ordered.map((node, index) => {
          const depth = outlineDepth(node, nodes);
          return (
            <div
              className={`outline-row ${selectedId === node.id ? "selected" : ""}`}
              key={node.id}
              draggable={canEdit}
              onDragStart={canEdit ? (event) => event.dataTransfer.setData("text/plain", node.id) : undefined}
              onDragOver={canEdit ? (event) => event.preventDefault() : undefined}
              onDrop={canEdit ? (event) => {
                event.preventDefault();
                const sourceId = event.dataTransfer.getData("text/plain");
                if (sourceId) onMove(nodes.find((item) => item.id === sourceId) ?? node, node.parent_id, index);
              } : undefined}
              style={{ paddingLeft: `${12 + depth * 16}px` }}
            >
              <button className="outline-title" type="button" onClick={() => onSelect(node)}>
                <span className="outline-kind">{node.kind === "subsection" ? "↳" : "§"}</span>
                <span>{node.title}</span>
              </button>
              {canEdit ? <div className="outline-actions">
                {node.kind === "section" ? <button type="button" onClick={() => onAdd(node.id, "subsection")} aria-label="Ajouter une sous-section">+</button> : null}
                <button type="button" onClick={() => onMove(node, node.parent_id, Math.max(0, node.position - 1))} aria-label="Monter">↑</button>
                <button type="button" onClick={() => onMove(node, node.parent_id, node.position + 1)} aria-label="Descendre">↓</button>
                <button type="button" onClick={() => onRename(node)} aria-label="Renommer">✎</button>
                <button type="button" onClick={() => onDuplicate(node)} aria-label="Dupliquer">⧉</button>
                <button type="button" onClick={() => onDelete(node)} aria-label="Supprimer">×</button>
              </div> : null}
            </div>
          );
        })}
      </div>
    </aside>
  );
}
