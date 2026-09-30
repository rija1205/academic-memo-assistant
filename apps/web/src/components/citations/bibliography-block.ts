import { Node, mergeAttributes } from "@tiptap/core";

/**
 * The bibliography block of the editor.
 *
 * The block is a *placeholder*: its text is generated from the citations actually present in
 * the document. The author never types inside it and cannot break its structure, and the
 * generated lines are not a source of truth — they are recomputed by the style engine, so
 * correcting a reference updates the block without touching the document.
 */
export interface BibliographyBlockAttrs {
  blockId: string;
  /** Heading shown above the generated entries. */
  title: string;
  style: string;
  entryCount: number;
  uncitedCount: number;
  orphanCount: number;
  /** Lines produced by the server; never edited. */
  lines: string[];
  generatedAt: string | null;
  isStale: boolean;
}

export const BIBLIOGRAPHY_BLOCK_NAME = "bibliographyBlock";

export const BibliographyBlock = Node.create({
  name: BIBLIOGRAPHY_BLOCK_NAME,
  group: "block",
  atom: true,
  selectable: true,
  draggable: false,

  addAttributes() {
    return {
      blockId: { default: "" },
      title: { default: "Bibliographie" },
      style: { default: "" },
      entryCount: { default: 0 },
      uncitedCount: { default: 0 },
      orphanCount: { default: 0 },
      lines: { default: [] as string[] },
      generatedAt: { default: null },
      isStale: { default: false },
    };
  },

  parseHTML() {
    return [
      {
        tag: `div[data-academic-node="${BIBLIOGRAPHY_BLOCK_NAME}"]`,
        getAttrs: (element) => {
          const node = element as HTMLElement;
          return {
            blockId: node.getAttribute("data-block-id") ?? "",
            title: node.getAttribute("data-title") ?? "Bibliographie",
            style: node.getAttribute("data-style") ?? "",
            entryCount: Number(node.getAttribute("data-entry-count") ?? 0),
            uncitedCount: Number(node.getAttribute("data-uncited-count") ?? 0),
            orphanCount: Number(node.getAttribute("data-orphan-count") ?? 0),
            lines: (node.getAttribute("data-lines") ?? "").split("\n").filter(Boolean),
            generatedAt: node.getAttribute("data-generated-at"),
            isStale: node.getAttribute("data-stale") === "true",
          };
        },
      },
    ];
  },

  renderHTML({ node, HTMLAttributes }) {
    const attrs = node.attrs as BibliographyBlockAttrs;
    return [
      "div",
      mergeAttributes(HTMLAttributes, {
        "data-academic-node": BIBLIOGRAPHY_BLOCK_NAME,
        "data-block-id": attrs.blockId || undefined,
        "data-title": attrs.title,
        "data-style": attrs.style || undefined,
        "data-entry-count": String(attrs.entryCount),
        "data-uncited-count": String(attrs.uncitedCount),
        "data-orphan-count": String(attrs.orphanCount),
        "data-lines": attrs.lines.join("\n") || undefined,
        "data-generated-at": attrs.generatedAt ?? undefined,
        "data-stale": attrs.isStale ? "true" : undefined,
        class: `bibliography-block${attrs.isStale ? " bibliography-block--stale" : ""}`,
      }),
      [ "div", { class: "bibliography-block__title" }, attrs.title ],
      attrs.lines.length
        ? [
            "ol",
            { class: "bibliography-block__list" },
            ...attrs.lines.map((line) => ["li", { class: "bibliography-block__entry" }, line]),
          ]
        : [
            "p",
            { class: "bibliography-block__empty" },
            "Aucune référence citée dans ce document pour l'instant.",
          ],
      attrs.orphanCount > 0
        ? [
            "p",
            { class: "bibliography-block__warning" },
            `${attrs.orphanCount} citation(s) invalide(s) : référence introuvable.`,
          ]
        : "",
    ];
  },
});

export function buildBibliographyContent(input: {
  blockId: string;
  title?: string;
  style: string;
  lines: string[];
  entryCount: number;
  uncitedCount: number;
  orphanCount: number;
  generatedAt: string;
  isStale?: boolean;
}): Record<string, unknown> {
  return {
    type: BIBLIOGRAPHY_BLOCK_NAME,
    attrs: {
      blockId: input.blockId,
      title: input.title ?? "Bibliographie",
      style: input.style,
      entryCount: input.entryCount,
      uncitedCount: input.uncitedCount,
      orphanCount: input.orphanCount,
      lines: input.lines,
      generatedAt: input.generatedAt,
      isStale: input.isStale ?? false,
    },
  };
}
