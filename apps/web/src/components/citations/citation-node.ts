import { Node, mergeAttributes } from "@tiptap/core";

/**
 * The Tiptap node of an academic citation.
 *
 * The node stores **identity, not text**: `citationId` points at the `citations` row and
 * `referenceIds` holds the real entries of `bibliographic_references`. The visible string is
 * produced by the style engine on the server, which is why changing the style or correcting
 * the year of a reference updates every citation without touching a single document.
 *
 * The rendered HTML keeps the data attributes, so a document exported to HTML, PDF or DOCX
 * later still carries the identifiers needed to re-render the citation.
 */
export interface CitationNodeAttrs {
  citationId: string;
  referenceIds: string[];
  mode: "parenthetical" | "narrative";
  locatorType: string | null;
  locatorValue: string | null;
  prefix: string | null;
  suffix: string | null;
  /** Text produced by the server. Never edited, never the source of truth. */
  text: string;
  /** True when the citation points at a reference that no longer exists. */
  isOrphaned: boolean;
  warnings: string[];
  /**
   * Stage 3 shipped a placeholder node that only held a free-text key. It is kept readable
   * as `legacyValue` so an old document still loads, and it is reported as unregistered
   * because a free-text key is not a reference identifier.
   */
  legacyValue: string | null;
}

export const CITATION_NODE_NAME = "citation";

function parseIdList(value: unknown): string[] {
  if (Array.isArray(value)) {
    return value.filter((item): item is string => typeof item === "string" && item.length > 0);
  }
  if (typeof value === "string" && value.length > 0) {
    return value.split(",").map((item) => item.trim()).filter(Boolean);
  }
  return [];
}

export const CitationNode = Node.create({
  name: CITATION_NODE_NAME,
  group: "inline",
  inline: true,
  atom: true,
  selectable: true,

  addAttributes() {
    return {
      citationId: { default: "" },
      referenceIds: { default: [] as string[] },
      mode: { default: "parenthetical" as const },
      locatorType: { default: null },
      locatorValue: { default: null },
      prefix: { default: null },
      suffix: { default: null },
      text: { default: "" },
      isOrphaned: { default: false },
      warnings: { default: [] as string[] },
      legacyValue: { default: null },
    };
  },

  parseHTML() {
    return [
      {
        tag: `span[data-academic-node="${CITATION_NODE_NAME}"]`,
        getAttrs: (element) => {
          const node = element as HTMLElement;
          return {
            citationId: node.getAttribute("data-citation-id") ?? "",
            referenceIds: parseIdList(node.getAttribute("data-reference-ids")),
            mode: node.getAttribute("data-mode") ?? "parenthetical",
            locatorType: node.getAttribute("data-locator-type"),
            locatorValue: node.getAttribute("data-locator-value"),
            prefix: node.getAttribute("data-prefix"),
            suffix: node.getAttribute("data-suffix"),
            text: node.textContent ?? "",
            isOrphaned: node.getAttribute("data-orphaned") === "true",
            warnings: parseIdList(node.getAttribute("data-warnings")),
            legacyValue: node.getAttribute("data-legacy-value"),
          };
        },
      },
    ];
  },

  renderHTML({ node, HTMLAttributes }) {
    const attrs = node.attrs as CitationNodeAttrs;
    const label = attrs.text || (attrs.legacyValue ? `[${attrs.legacyValue}]` : "[Citation]");
    return [
      "span",
      mergeAttributes(HTMLAttributes, {
        "data-academic-node": CITATION_NODE_NAME,
        "data-citation-id": attrs.citationId || undefined,
        "data-reference-ids": attrs.referenceIds.length ? attrs.referenceIds.join(",") : undefined,
        "data-mode": attrs.mode,
        "data-locator-type": attrs.locatorType ?? undefined,
        "data-locator-value": attrs.locatorValue ?? undefined,
        "data-prefix": attrs.prefix ?? undefined,
        "data-suffix": attrs.suffix ?? undefined,
        "data-orphaned": attrs.isOrphaned ? "true" : undefined,
        "data-warnings": attrs.warnings.length ? attrs.warnings.join(" | ") : undefined,
        "data-legacy-value": attrs.legacyValue ?? undefined,
        class: [
          "citation-node",
          attrs.isOrphaned ? "citation-node--orphaned" : "",
          attrs.mode === "narrative" ? "citation-node--narrative" : "",
        ]
          .filter(Boolean)
          .join(" "),
        title: attrs.warnings.length ? attrs.warnings.join(" · ") : undefined,
        "aria-label": attrs.isOrphaned ? "Citation invalide" : `Citation ${label}`,
      }),
      label,
    ];
  },
});

/** Build the JSON of a citation node, ready to be inserted with `insertContent`. */
export function buildCitationContent(input: {
  citationId: string;
  referenceIds: string[];
  text: string;
  mode?: "parenthetical" | "narrative";
  locatorType?: string | null;
  locatorValue?: string | null;
  prefix?: string | null;
  suffix?: string | null;
  isOrphaned?: boolean;
  warnings?: string[];
}): Record<string, unknown> {
  return {
    type: CITATION_NODE_NAME,
    attrs: {
      citationId: input.citationId,
      referenceIds: input.referenceIds,
      mode: input.mode ?? "parenthetical",
      locatorType: input.locatorType ?? null,
      locatorValue: input.locatorValue ?? null,
      prefix: input.prefix ?? null,
      suffix: input.suffix ?? null,
      text: input.text,
      isOrphaned: input.isOrphaned ?? false,
      warnings: input.warnings ?? [],
      legacyValue: null,
    },
  };
}

/** Read the citation nodes of a document, in document order. */
export function collectCitations(content: unknown): CitationNodeAttrs[] {
  const found: CitationNodeAttrs[] = [];
  const walk = (node: unknown): void => {
    if (Array.isArray(node)) {
      node.forEach(walk);
      return;
    }
    if (!node || typeof node !== "object") return;
    const record = node as { type?: string; attrs?: unknown; content?: unknown };
    if (record.type === CITATION_NODE_NAME) {
      found.push(record.attrs as CitationNodeAttrs);
    }
    walk(record.content);
  };
  if (content && typeof content === "object") {
    walk((content as { content?: unknown }).content);
  }
  return found;
}

/** True when the node is a stage 3 placeholder that carries only a free-text key. */
export function isLegacyCitation(attrs: CitationNodeAttrs): boolean {
  return !attrs.citationId && Boolean(attrs.legacyValue);
}
