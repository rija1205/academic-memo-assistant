"use client";

import { Node, type Editor, type JSONContent } from "@tiptap/core";
import { EditorContent, useEditor } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import { Table } from "@tiptap/extension-table";
import TableCell from "@tiptap/extension-table-cell";
import TableHeader from "@tiptap/extension-table-header";
import TableRow from "@tiptap/extension-table-row";
import Image from "@tiptap/extension-image";
import Link from "@tiptap/extension-link";
import Placeholder from "@tiptap/extension-placeholder";
import { useEffect, useRef, useState } from "react";
import {
  WritingPanel,
  type EditorSelection,
} from "@/components/writing/writing-panel";
import {
  BibliographyBlock,
  buildBibliographyContent,
} from "@/components/citations/bibliography-block";
import {
  CitationNode,
  buildCitationContent,
  collectCitations,
  type CitationNodeAttrs,
} from "@/components/citations/citation-node";
import { CitationPicker } from "@/components/citations/citation-picker";
import {
  CitationEditorPanel,
} from "@/components/citations/citation-editor-panel";
import {
  ApiError,
  deleteCitation,
  detachCitationReference,
  getCitation,
  getRenderedBibliography,
  getRenderedCitations,
  reconcileCitations,
  saveSectionContent,
  upsertCitation,
  type Citation,
  type CitationItemInput,
  type LocatorType,
  type Section,
  type SectionStatus,
} from "@/lib/api";

function academicAtom(name: string, label: string) {
  return Node.create({
    name,
    group: "inline",
    inline: true,
    atom: true,
    addAttributes() {
      return { value: { default: label } };
    },
    parseHTML() {
      return [{ tag: `span[data-academic-node="${name}"]` }];
    },
    renderHTML({ HTMLAttributes }) {
      return [
        "span",
        {
          ...HTMLAttributes,
          "data-academic-node": name,
          class: `academic-node academic-node--${name}`,
        },
        HTMLAttributes.value || label,
      ];
    },
  });
}

const Equation = academicAtom("equation", "Équation");
const Reference = academicAtom("reference", "Référence");

const PageBreak = Node.create({
  name: "pageBreak",
  group: "block",
  atom: true,
  addAttributes() {
    return { class: { default: "academic-page-break" } };
  },
  parseHTML() {
    return [{ tag: "div.academic-page-break" }];
  },
  renderHTML({ HTMLAttributes }) {
    return ["div", { ...HTMLAttributes, "aria-label": "Saut de page" }];
  },
});

function editorExtensions() {
  return [
    StarterKit,
    Table.configure({ resizable: true }),
    TableRow,
    TableHeader,
    TableCell,
    Image,
    Link.configure({ openOnClick: false, autolink: true }),
    Placeholder.configure({ placeholder: "Commencez à écrire votre section…" }),
    Equation,
    Reference,
    PageBreak,
    CitationNode,
    BibliographyBlock,
  ];
}

export function SectionEditor({ section, onSaved, readOnly = false }: { section: Section; onSaved?: (section: Section) => void; readOnly?: boolean }) {
  const [saveState, setSaveState] = useState<"saved" | "saving" | "error">("saved");
  const [error, setError] = useState("");
  const [draftAvailable, setDraftAvailable] = useState(false);
  const draftKey = `ama-draft:${section.id}`;
  const version = useRef(section.version);
  const saveTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const saveInFlight = useRef(false);
  const pendingSave = useRef(false);
  const saveNowRef = useRef<() => void>(() => undefined);
  const editorRef = useRef<Editor | null>(null);
  const [selection, setSelection] = useState<EditorSelection>({ from: 0, to: 0, text: "" });
  const [writingOpen, setWritingOpen] = useState(false);
  // Stage 10 - citations. The picker creates a node; the server owns the rendered text.
  const [pickerOpen, setPickerOpen] = useState(false);
  const [activeCitation, setActiveCitation] = useState<Citation | null>(null);
  const [orphanNodes, setOrphanNodes] = useState<string[]>([]);
  const [styleLabel, setStyleLabel] = useState("");
  const [citationNotice, setCitationNotice] = useState("");
  const editor = useEditor({
    extensions: editorExtensions(),
    content: section.content as JSONContent,
    editable: !readOnly,
    immediatelyRender: false,
    onUpdate: ({ editor: currentEditor }) => {
      pendingSave.current = true;
      try {
        window.localStorage.setItem(draftKey, JSON.stringify(currentEditor.getJSON()));
      } catch {
        // Local recovery is best effort when storage is unavailable.
      }
      setSaveState("saving");
      if (saveTimer.current) clearTimeout(saveTimer.current);
      saveTimer.current = setTimeout(() => saveNowRef.current(), 1200);
    },
    onSelectionUpdate: ({ editor: currentEditor }) => {
      const { from, to, empty } = currentEditor.state.selection;
      const text = empty ? "" : currentEditor.state.doc.textBetween(from, to, " ");
      setSelection({ from, to, text });
    },
    onTransaction: ({ editor: currentEditor }) => {
      // Clicking a citation opens its editor. The node carries its citationId in its
      // attributes, so no text search is needed and a rendered string can never be mistaken
      // for an identifier.
      const { $from } = currentEditor.state.selection;
      if (!currentEditor.state.selection.empty) return;
      for (let depth = $from.depth; depth > 0; depth -= 1) {
        const node = $from.node(depth);
        if (node.type.name !== "citation") continue;
        const nodeId = (node.attrs as CitationNodeAttrs).citationId;
        if (nodeId) void openCitationForNode(nodeId);
        return;
      }
    },
  });
  editorRef.current = editor;

  useEffect(() => {
    editor?.setEditable(!readOnly);
  }, [editor, readOnly]);

  // Opening a section shows the text the server produces for its citations, so a document
  // written before a reference was corrected immediately displays the corrected form.
  useEffect(() => {
    if (!editor) return;
    let cancelled = false;
    void getRenderedCitations(section.project_id, section.id)
      .then((rendered) => {
        if (cancelled) return;
        setStyleLabel(rendered.style_label);
        setOrphanNodes(rendered.orphaned);
        applyRenderedCitations(rendered.citations);
      })
      .catch(() => {
        // Keep the stored text; the next save reconciles.
      });
    return () => {
      cancelled = true;
    };
  }, [editor, section.id, section.project_id]);

  useEffect(() => {
    if (section.version !== version.current) {
      version.current = section.version;
      editor?.commands.setContent(section.content as JSONContent, { emitUpdate: false });
    }
    setError("");
    setSaveState("saved");
    try {
      setDraftAvailable(Boolean(window.localStorage.getItem(draftKey)));
    } catch {
      setDraftAvailable(false);
    }
  }, [draftKey, editor, section.id, section.content, section.version]);

  useEffect(() => {
    const handleOnline = () => {
      if (pendingSave.current) saveNowRef.current();
    };
    window.addEventListener("online", handleOnline);
    return () => window.removeEventListener("online", handleOnline);
  }, [section.id]);

  useEffect(() => () => {
    if (saveTimer.current) clearTimeout(saveTimer.current);
  }, []);

  async function saveNow(statusOverride?: SectionStatus) {
    const currentEditor = editorRef.current;
    if (!currentEditor || saveInFlight.current) return;
    saveInFlight.current = true;
    pendingSave.current = false;
    if (saveTimer.current) clearTimeout(saveTimer.current);
    try {
      setError("");
      const saved = await saveSectionContent(section.project_id, section.id, {
        content: currentEditor.getJSON() as Record<string, unknown>,
        plain_text: currentEditor.getText(),
        status: statusOverride,
        expected_version: version.current,
      });
      version.current = saved.version;
      try {
        window.localStorage.removeItem(draftKey);
      } catch {
        // Ignore storage cleanup failures.
      }
      setSaveState("saved");
      onSaved?.(saved);
      // The document is saved, so its citation nodes are registered and the rendered text can
      // be refreshed. A failure here never loses the author's text: the node keeps the string
      // it was inserted with, and the next save retries.
      if (!readOnly) {
        void syncCitations(saved);
      }
    } catch (cause) {
      setSaveState("error");
      setError(cause instanceof ApiError ? cause.message : "Sauvegarde impossible.");
    } finally {
      saveInFlight.current = false;
      if (pendingSave.current) {
        saveTimer.current = setTimeout(() => void saveNow(), 600);
      }
    }
  }

  saveNowRef.current = () => void saveNow();

  function recoverDraft() {
    if (!editor) return;
    try {
      const raw = window.localStorage.getItem(draftKey);
      if (!raw) return;
      editor.commands.setContent(JSON.parse(raw));
      setDraftAvailable(false);
      setSaveState("saving");
    } catch {
      setError("Brouillon local illisible.");
    }
  }

  function applyInsertion(text: string) {
    editor?.chain().focus().insertContent(text).run();
  }

  function applyReplacement(text: string) {
    const currentEditor = editorRef.current;
    if (!currentEditor) return;
    const { from, to } = currentEditor.state.selection;
    if (from === to) {
      currentEditor.chain().focus().insertContent(text).run();
      return;
    }
    currentEditor.chain().focus().insertContentAt({ from, to }, text).run();
  }

  function insertAcademicPlaceholder(label: string) {
    editor?.chain().focus().insertContent(`[${label}] `).run();
  }

  function insertEquation() {
    const value = window.prompt("Expression ou identifiant LaTeX");
    if (value?.trim()) editor?.chain().focus().insertContent({ type: "equation", attrs: { value: value.trim() } }).run();
  }

  function insertReference() {
    const value = window.prompt("Clé de référence bibliographique");
    if (value?.trim()) editor?.chain().focus().insertContent({ type: "reference", attrs: { value: value.trim() } }).run();
  }

  function insertImage() {
    const url = window.prompt("URL de l'image");
    if (!url) return;
    try {
      const parsed = new URL(url);
      if (!['http:', 'https:'].includes(parsed.protocol)) throw new Error('unsupported');
      editor?.chain().focus().setImage({ src: parsed.toString(), alt: "Illustration" }).run();
    } catch {
      setError("Utilisez une URL HTTP ou HTTPS pour l'image.");
    }
  }

  function insertLink() {
    const url = window.prompt("URL du lien");
    if (url) editor?.chain().focus().setLink({ href: url }).run();
  }

  /* ------------------------------------------------- stage 10 : citations */

  /** Re-render the citations of this section after the author edited one of them. */
  async function refreshRenderedText() {
    const currentEditor = editorRef.current;
    if (!currentEditor) return;
    try {
      const rendered = await getRenderedCitations(section.project_id, section.id);
      setOrphanNodes(rendered.orphaned);
      applyRenderedCitations(rendered.citations);
    } catch {
      // The node keeps the string it had; the next save re-registers and re-renders it.
    }
  }

  /**
   * Push the server-rendered text onto every citation node of the document.
   *
   * The text is written into the node only so the editor can display it; the source of truth
   * stays `citationId` + `referenceIds`. That is why a later correction of a reference is
   * picked up by the next refresh without the author touching the paragraph.
   */
  function applyRenderedCitations(
    rendered: { node_id: string; text: string; is_orphaned: boolean; warnings: string[] }[],
  ) {
    const currentEditor = editorRef.current;
    if (!currentEditor) return;
    const byNode = new Map(rendered.map((item) => [item.node_id, item]));

    // Attributes are replaced through a transaction rather than by writing into ``node.attrs``,
    // which Tiptap types as read-only and which would leave the document unaware of the change.
    const transaction = currentEditor.state.tr;
    let changed = false;
    currentEditor.state.doc.descendants((node, position) => {
      if (node.type.name !== "citation") return;
      const attrs = node.attrs as CitationNodeAttrs;
      const match = byNode.get(attrs.citationId);
      if (!match) return;
      if (
        attrs.text === match.text &&
        attrs.isOrphaned === match.is_orphaned &&
        (attrs.warnings ?? []).join("|") === match.warnings.join("|")
      ) {
        return;
      }
      transaction.setNodeMarkup(position, undefined, {
        ...attrs,
        text: match.text,
        isOrphaned: match.is_orphaned,
        warnings: match.warnings,
      });
      changed = true;
    });
    if (!changed) return;
    // emitUpdate false: refreshing the display is not an author edit, so it must not trigger
    // another autosave and bump the section version for nothing.
    currentEditor.view.dispatch(transaction.setMeta("addToHistory", false));
  }

  /** Register the citations of a saved document, then refresh the rendered text. */
  async function syncCitations(saved: Section) {
    const currentEditor = editorRef.current;
    if (!currentEditor) return;
    try {
      const check = await reconcileCitations(saved.project_id, saved.id, currentEditor.getJSON());
      setStyleLabel(check.style);
      setOrphanNodes(check.orphaned_node_ids);
      applyRenderedCitations(check.citations);
      if (check.unregistered_node_ids.length > 0) {
        // A stage 3 placeholder carried only a free-text key. It is reported, never guessed
        // into a reference, because a key is not an identifier.
        setCitationNotice(
          `${check.unregistered_node_ids.length} citation(s) sans reference : ` +
            "utilisez \u00ab Inserer une citation \u00bb pour les rattacher.",
        );
      } else {
        setCitationNotice("");
      }
    } catch {
      // Synchronisation is a convenience: the text stays as inserted and the next save retries.
    }
  }

  /** Insert a citation node using the text the server just produced. */
  async function confirmCitation(input: {
    items: CitationItemInput[];
    prefix: string;
    suffix: string;
    locatorType: LocatorType | null;
    locatorValue: string;
    mode: "parenthetical" | "narrative";
    preview: { citation: string; warnings: string[] };
  }) {
    const currentEditor = editorRef.current;
    if (!currentEditor) return;
    const nodeId = `cit-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
    try {
      const saved = await upsertCitation(section.project_id, {
        section_id: section.id,
        node_id: nodeId,
        items: input.items,
        prefix: input.prefix || null,
        suffix: input.suffix || null,
        locator_type: input.locatorType,
        locator_value: input.locatorValue || null,
        mode: input.mode,
        position_in_section: collectCitations(currentEditor.getJSON()).length,
      });
      currentEditor
        .chain()
        .focus()
        .insertContent([
          buildCitationContent({
            citationId: nodeId,
            referenceIds: input.items.map((item) => item.reference_id),
            text: saved.rendered_text || input.preview.citation,
            mode: input.mode,
            locatorType: input.locatorType,
            locatorValue: input.locatorValue || null,
            prefix: input.prefix || null,
            suffix: input.suffix || null,
            isOrphaned: saved.is_orphaned,
            warnings: saved.warnings,
          }),
          { type: "text", text: " " },
        ])
        .run();
      setPickerOpen(false);
      setCitationNotice("");
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Citation impossible.");
    }
  }

  /** Load the citation attached to a node when the author clicks it. */
  async function openCitationForNode(nodeId: string) {
    try {
      const list = await getRenderedCitations(section.project_id, section.id);
      setStyleLabel(list.style_label);
      setOrphanNodes(list.orphaned);
      const match = list.citations.find((item) => item.node_id === nodeId);
      if (!match?.citation_id) return;
      setActiveCitation(await getCitation(section.project_id, match.citation_id));
    } catch {
      setActiveCitation(null);
    }
  }

  /** Insert or refresh the generated bibliography block. */
  async function insertBibliography() {
    const currentEditor = editorRef.current;
    if (!currentEditor) return;
    try {
      const rendered = await getRenderedBibliography(section.project_id);
      const block = buildBibliographyContent({
        blockId: `bib-${section.id.slice(0, 8)}`,
        style: rendered.style,
        lines: rendered.entries.map((entry) => entry.text),
        entryCount: rendered.cited_count,
        uncitedCount: rendered.uncited_count,
        orphanCount: rendered.orphaned_citations.length,
        generatedAt: new Date().toISOString(),
      });
      currentEditor.chain().focus().insertContent([{ type: "paragraph" }, block]).run();
      setCitationNotice(
        `Bibliographie ${rendered.style_label} : ${rendered.cited_count} reference(s) citee(s), ` +
          `${rendered.uncited_count} non citee(s).` +
          (rendered.incomplete_count > 0
            ? ` ${rendered.incomplete_count} entree(s) avec information manquante.`
            : ""),
      );
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Bibliographie impossible.");
    }
  }

  if (!editor) return <div className="editor-loading">Chargement de l&apos;éditeur…</div>;

  return (
    <section className="editor-panel" aria-label="Éditeur de contenu">
      {!readOnly ? <div className="editor-toolbar" role="toolbar" aria-label="Mise en forme">
        <button type="button" onClick={() => editor.chain().focus().toggleBold().run()} aria-label="Gras">G</button>
        <button type="button" onClick={() => editor.chain().focus().toggleItalic().run()} aria-label="Italique">I</button>
        <button type="button" onClick={() => editor.chain().focus().toggleHeading({ level: 2 }).run()}>H2</button>
        <button type="button" onClick={() => editor.chain().focus().toggleBulletList().run()}>Liste</button>
        <button type="button" onClick={() => editor.chain().focus().toggleOrderedList().run()}>1.</button>
        <button type="button" onClick={() => editor.chain().focus().toggleBlockquote().run()}>Citation</button>
        <button type="button" onClick={() => editor.chain().focus().insertTable({ rows: 3, cols: 3, withHeaderRow: true }).run()}>Tableau</button>
        <button type="button" onClick={insertImage}>Image</button>
        <button type="button" onClick={() => insertAcademicPlaceholder("Légende de l'illustration")}>Légende</button>
        <button type="button" onClick={insertLink}>Lien</button>
        <button type="button" onClick={() => editor.chain().focus().setHorizontalRule().run()}>Séparateur</button>
        <button type="button" onClick={() => editor.chain().focus().insertContent({ type: "pageBreak" }).run()}>Saut de page</button>
        <button type="button" onClick={insertEquation}>Équation</button>
        <button type="button" onClick={() => setPickerOpen((open) => !open)}>Inserer une citation</button>
        <button type="button" onClick={() => void insertBibliography()}>Inserer / actualiser la bibliographie</button>
        <button type="button" onClick={insertReference}>Référence</button>
        <span className="toolbar-spacer" />
        <button type="button" onClick={() => void saveNow("complete")}>Section terminée</button>
        <button type="button" disabled title="IA bientôt disponible">Demander à l&apos;IA</button>
        <button type="button" disabled title="IA bientôt disponible">Reformuler</button>
      </div> : <div className="editor-readonly">Mode lecture seule · vous pouvez consulter le contenu.</div>}
      <div className="editor-status-row">
        <span className={`save-indicator save-indicator--${saveState}`}>
          {saveState === "saving" ? "Enregistrement…" : saveState === "error" ? "Erreur de sauvegarde" : "Enregistré"}
        </span>
        <span>{section.word_count} mots · version {version.current}</span>
      </div>
      {error ? <p className="form-error editor-error" role="alert">{error}</p> : null}
      {draftAvailable ? <div className="draft-recovery"><span>Un brouillon local non sauvegardé est disponible.</span><button type="button" onClick={recoverDraft}>Récupérer</button></div> : null}
      <EditorContent editor={editor} className="academic-editor" />
      {citationNotice ? <p className="citation-notice">{citationNotice}</p> : null}
      {orphanNodes.length > 0 ? (
        <p className="citation-orphan-warning" role="alert">
          {orphanNodes.length} citation(s) pointent vers une reference supprimee. Ouvrez-les
          pour les reparer : aucune reference n&apos;est inventee.
        </p>
      ) : null}
      {styleLabel ? <p className="citation-style-label">Style bibliographique : {styleLabel}</p> : null}
      {pickerOpen && !readOnly ? (
        <CitationPicker
          projectId={section.project_id}
          onCancel={() => setPickerOpen(false)}
          onConfirm={(input) => void confirmCitation(input)}
        />
      ) : null}
      {activeCitation ? (
        <CitationEditorPanel
          citation={activeCitation}
          onClose={() => setActiveCitation(null)}
          onSaved={(updated) => {
            setActiveCitation(updated);
            void refreshRenderedText();
          }}
          onDeleted={() => {
            setActiveCitation(null);
            void refreshRenderedText();
          }}
        />
      ) : null}
      {writingOpen ? (
        <WritingPanel
          projectId={section.project_id}
          sectionId={section.id}
          selection={selection}
          sectionText={editor?.getText() ?? ""}
          onInsert={applyInsertion}
          onReplace={applyReplacement}
        />
      ) : null}
    </section>
  );
}

export function sectionStatusLabel(status: SectionStatus): string {
  if (status === "complete") return "Complétée";
  if (status === "in_progress") return "En cours";
  return "Vide";
}
