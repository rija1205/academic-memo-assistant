"""Catalogue of academic writing actions.

Each action declares what it needs and what it must never do. Keeping this declarative rather
than scattering prompt strings across the router means a new action is one entry, and the
frontend can render the available actions without hard-coding a list.

Two flags drive the pipeline:

* ``uses_sources`` - the action needs the RAG engine, so the retrieved passages are put in the
  prompt and their citations are validated. Actions such as *reformuler* do not need sources:
  rewriting a sentence must not drag external material into the author's own text.
* ``returns_proposal`` - every action returns a proposal. The backend never writes to the
  thesis. Applying a proposal is always an explicit user action in the editor.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class WritingAction(StrEnum):
    """The writing operations offered to the author."""

    REPHRASE = "rephrase"
    CORRECT = "correct"
    ACADEMIC_STYLE = "academic_style"
    SUMMARIZE = "summarize"
    EXPAND = "expand"
    CONDENSE = "condense"
    TRANSLATE = "translate"
    EXPLAIN = "explain"
    TRANSITION = "transition"
    ANALYZE_SECTION = "analyze_section"
    VERIFY_CLAIMS = "verify_claims"
    WRITE_FROM_SOURCES = "write_from_sources"


@dataclass(frozen=True, slots=True)
class ActionSpec:
    """Declarative description of one writing action."""

    action: WritingAction
    label: str
    description: str
    instruction: str
    uses_sources: bool
    needs_selection: bool
    needs_full_section: bool = False
    expects_english_output: bool = False
    #: Free-form suggestions shown under the result, tailored to the action.
    output_contract: str = ""

    @property
    def requires_sources(self) -> bool:
        return self.uses_sources


_SHARED_RULES = """
Tu es un assistant de redaction academique francophone.

REGLES ABSOLUES
- Tu produis une PROPOSITION. Tu n'ecris jamais directement dans le memoire.
- Tu ne modifies pas le texte de l'auteur ailleurs que dans la portion demandee.
- Tu n'inventes jamais un auteur, une annee, un DOI, un chiffre, un resultat scientifique,
  une citation ni une reference bibliographique.
- Si une information n'est pas presente dans les sources fournies, ecris
  « Non etabli par les sources disponibles ».
- Si le texte fourni est trop insuffisant pour exeuter l'action, dis-le clairement au lieu
  de produire un texte de remplissage.
- Conserve le sens de l'auteur. Ne transforme pas une opinion en fait etabli.
- Respecte l'orthographe, la typographie francaise (espaces insécables avant : ; ! ?) et les
  conventions academiques.
- Utilise des marqueurs [CITATION:SRC-xxx] uniquement pour les passages fournis en contexte.
""".strip()


_SPECS: tuple[ActionSpec, ...] = (
    ActionSpec(
        action=WritingAction.REPHRASE,
        label="Reformuler",
        description="Réécrit la sélection avec d'autres mots, sans changer le sens.",
        instruction=(
            "Reformule le texte de l'auteur avec une formulation differente, plus claire et plus "
            "fluide. Conserve strictement le sens, les nuances et le niveau de langage. "
            "N'ajoute aucune information nouvelle."
        ),
        uses_sources=False,
        needs_selection=True,
    ),
    ActionSpec(
        action=WritingAction.CORRECT,
        label="Corriger",
        description="Corrige la grammaire, l'orthographe et la typographie.",
        instruction=(
            "Corrige uniquement les erreurs de grammaire, d'orthographe, de syntaxe et de "
            "typographie francaise. Ne reformule pas, n'ameliore pas le style, ne supprime rien. "
            "Si le texte est correct, renvoie-le tel quel."
        ),
        uses_sources=False,
        needs_selection=True,
    ),
    ActionSpec(
        action=WritingAction.ACADEMIC_STYLE,
        label="Style académique",
        description="Passe la sélection dans un registre académique soutenu.",
        instruction=(
            "Reformule le texte dans un registre academique soutenu et sobre : precision "
            "lexicale, construction nominale lorsque c'est pertinent, suppression des tics "
            "d'oralite. Conserve le sens et les limites des affirmations. N'exagere aucune "
            "portee : un resultat preliminaire reste preliminaire."
        ),
        uses_sources=False,
        needs_selection=True,
    ),
    ActionSpec(
        action=WritingAction.SUMMARIZE,
        label="Résumer",
        description="Produit un résumé fidèle de la sélection.",
        instruction=(
            "Reduis le texte a l'essentiel en conservant tout ce qui porte l'information : les "
            "resultats, les chiffres, les limites, les conditions. Ne conclus pas au-dela de ce "
            "que le texte etablit."
        ),
        uses_sources=False,
        needs_selection=True,
    ),
    ActionSpec(
        action=WritingAction.EXPAND,
        label="Développer",
        description="Développe la sélection en conservant fidèlement les idées.",
        instruction=(
            "Developpe le texte : precise les transitions, articule les idees et explicite les "
            "sous-arguments qui sont implicites. N'ajoute aucun fait, chiffre, auteur ou "
            "reference qui ne soit pas dans le texte ou dans les sources fournies."
        ),
        uses_sources=False,
        needs_selection=True,
    ),
    ActionSpec(
        action=WritingAction.CONDENSE,
        label="Réduire",
        description="Raccourcit la sélection sans perdre d'information essentielle.",
        instruction=(
            "Reduis la longueur du texte d'environ un tiers en supprimant les repetitions et les "
            "developpements redondants. Conserve tous les elements porteurs de sens. Ne supprime "
            "aucune idee, nuance ou reserve."
        ),
        uses_sources=False,
        needs_selection=True,
    ),
    ActionSpec(
        action=WritingAction.TRANSLATE,
        label="Traduire",
        description="Traduit la sélection en anglais scientifique.",
        instruction=(
            "Traduis le texte de l'auteur en anglais scientifique soutenu, avec la terminologie "
            "specialisee du domaine. Ne commente pas la traduction, ne resume pas. Si un terme "
            "n'a pas d'equivalent fiable, garde le terme d'origine entre parentheses."
        ),
        uses_sources=False,
        needs_selection=True,
        expects_english_output=True,
    ),
    ActionSpec(
        action=WritingAction.EXPLAIN,
        label="Expliquer",
        description="Explique simplement la sélection, éventuellement à partir des sources.",
        instruction=(
            "Explique le contenu du texte de maniere plus simple et plus didactique, en conservant "
            "la rigueur. Si des sources sont fournies, appuie l'explication sur elles. Ne "
            "simplifie pas au point de devenir faux."
        ),
        uses_sources=True,
        needs_selection=True,
    ),
    ActionSpec(
        action=WritingAction.TRANSITION,
        label="Proposer une transition",
        description="Propose une transition entre le texte précédent et la sélection.",
        instruction=(
            "Reduis la transition en une ou deux phrases qui articulent logiquement le passage "
            "precedent et le texte selectionne. Ne resume pas le contenu : assure la continuite "
            "logique."
        ),
        uses_sources=False,
        needs_selection=True,
    ),
    ActionSpec(
        action=WritingAction.ANALYZE_SECTION,
        label="Analyser la section",
        description="Analyse la section entière : structure, clarté, lacunes.",
        instruction=(
            "Analyse la section en academicien, de maniere critique et constructive. Traite "
            "separement : la structure et la progression des idees, la precision du vocabulaire, "
            "la qualite des transitions, les lacunes argumentatives, les formulations qui "
            "restent a preciser. Ne reecris pas la section. Donne des observations eclairees par "
            "les sources fournies lorsqu'elles existent."
        ),
        uses_sources=True,
        needs_selection=False,
        needs_full_section=True,
        output_contract=(
            "Structure en rubriques : Structure, Precision du vocabulaire, Transitions, "
            "Lacunes argumentatives, A preciser. Sois specifique et cite les sources fournies "
            "quand elles sont pertinentes."
        ),
    ),
    ActionSpec(
        action=WritingAction.VERIFY_CLAIMS,
        label="Vérifier les affirmations",
        description="Confronte les affirmations de la sélection aux sources.",
        instruction=(
            "Confronte chaque affirmation du texte aux sources fournies. Classe-les en trois "
            "categories : CONFIRMEE par une source, NON CONFIRMEE (aucune source ne l'etaye), "
            "CONTREDITEE par une source. Cite la source, la page et le passage pour chaque "
            "affirmation confirmee ou contredite. N'invente jamais de source pour une affirmation "
            "non trouvee."
        ),
        uses_sources=True,
        needs_selection=True,
        output_contract=(
            "Une ligne par affirmation, prefixee par CONFIRMEE, NON CONFIRMEE ou CONTREDITEE, "
            "suivie de la source et de la page lorsqu'elle existe."
        ),
    ),
    ActionSpec(
        action=WritingAction.WRITE_FROM_SOURCES,
        label="Rédiger depuis les sources",
        description="Rédige un passage à partir des sources indexées du mémoire.",
        instruction=(
            "Reduis un passage academique en answering l'instruction de l'auteur, en "
            "t'appuyant STRICTEMENT sur les passages fournis. Chaque affirmation doit porter la "
            "citation du passage qui l'etaye. Si les sources ne permettent pas d'ecrire ce "
            "passage, dis-le clairement au lieu d'inventer."
        ),
        uses_sources=True,
        needs_selection=False,
        output_contract=(
            "Un ou plusieurs paragraphes academiques, chaque affirmation rattachee a une "
            "citation [CITATION:SRC-xxx]. Pas de titre, pas de plan, pas de bibliographie."
        ),
    ),
)

SPECS: dict[WritingAction, ActionSpec] = {spec.action: spec for spec in _SPECS}


def get_spec(action: WritingAction) -> ActionSpec:
    return SPECS[action]


def system_prompt(action: WritingAction) -> str:
    """Build the system prompt for one action."""
    spec = get_spec(action)
    parts = [_SHARED_RULES, "", f"ACTION DEMANDEE : {spec.label}", spec.instruction]
    if spec.output_contract:
        parts.extend(["", f"FORMAT DE SORTIE ATTENDU : {spec.output_contract}"])
    return "\n".join(parts)


def action_catalog() -> list[dict[str, object]]:
    """Catalogue exposed to the frontend so the UI is not hard-coded."""
    return [
        {
            "action": spec.action.value,
            "label": spec.label,
            "description": spec.description,
            "uses_sources": spec.uses_sources,
            "needs_selection": spec.needs_selection,
            "needs_full_section": spec.needs_full_section,
        }
        for spec in _SPECS
    ]


__all__ = [
    "ActionSpec",
    "SPECS",
    "WritingAction",
    "action_catalog",
    "get_spec",
    "system_prompt",
]
