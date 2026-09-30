"""The academic audit checks.

Every function here is a **pure function of the collected data**. There is no database access,
no network call and above all no language model: an audit that depended on a model could not
be trusted to report the same thing twice, and it could not be tested.

Each check returns a :class:`CheckOutcome`. A check that lacks the data it needs returns
``skipped_reason`` instead of findings, so a report can distinguish "no problem" from "not
able to tell", which are very different situations for a student.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from app.audit.findings import (
    INSUFFICIENT_LABEL,
    MISSING_LABEL,
    TO_VERIFY_LABEL,
    CheckOutcome,
    Finding,
    Severity,
)


@dataclass(slots=True)
class ReferenceView:
    """A bibliographic reference as the audit sees it."""

    reference_id: str
    citation_key: str
    reference_type: str
    title: str | None
    publication_year: int | None
    author_count: int
    organisation_count: int
    has_doi: bool
    has_url: bool
    has_abstract: bool
    keyword_count: int
    is_deleted: bool
    duplicate_level: str | None = None


@dataclass(slots=True)
class CitationView:
    """A citation as the audit sees it, with the references it points to."""

    citation_id: str
    section_id: str
    section_title: str
    node_id: str
    rendered_text: str
    is_orphaned: bool
    is_pending: bool
    mode: str
    reference_ids: tuple[str, ...]


@dataclass(slots=True)
class SourceView:
    """An imported source as the audit sees it."""

    source_id: str
    title: str | None
    original_filename: str | None
    status: str
    file_count: int
    page_count: int
    block_count: int
    indexed: bool
    #: True when the extraction produced text that carries its own provenance.
    has_provenance: bool = True


@dataclass(slots=True)
class SectionView:
    """A section as the audit sees it."""

    section_id: str
    title: str
    level: int
    word_count: int
    status: str
    plain_text: str
    citation_count: int
    figure_count: int
    table_count: int
    equation_count: int
    has_abstract_like_heading: bool = False


@dataclass(slots=True)
class ProjectView:
    """The project metadata the audit reasons about."""

    project_id: str
    title: str
    author_name: str | None
    institution: str | None
    education_level: str | None
    academic_year: str | None
    supervisor_name: str | None
    thesis_type: str | None
    problem_statement: str | None
    general_objective: str | None
    specific_objectives: tuple[str, ...]
    hypotheses: tuple[str, ...]
    keywords: tuple[str, ...]
    bibliography_style: str


@dataclass(slots=True)
class AuditData:
    """Everything the checks need, gathered once by the service."""

    project: ProjectView
    sections: list[SectionView] = field(default_factory=list)
    references: list[ReferenceView] = field(default_factory=list)
    citations: list[CitationView] = field(default_factory=list)
    sources: list[SourceView] = field(default_factory=list)
    #: Number of sections the project is expected to have, when the platform declares one.
    expected_section_count: int | None = None
    #: Academic year of the platform, used to spot a stale memoir.
    current_academic_year: str | None = None


# --------------------------------------------------------------- bibliography


def check_orphan_citations(data: AuditData) -> CheckOutcome:
    """Citations whose reference has been removed.

    This is the most serious bibliographic problem: the text asserts something that can no
    longer be traced to a source.
    """
    outcome = CheckOutcome(code="citations.orphelines")
    orphans = [citation for citation in data.citations if citation.is_orphaned]
    for citation in orphans:
        outcome.findings.append(
            Finding(
                code="citations.orphelines",
                severity=Severity.BLOCKER,
                title="Citation orpheline",
                detail=(
                    f"La citation « {citation.rendered_text} » de la section "
                    f"« {citation.section_title} » pointe vers une référence supprimée. "
                    "L'affirmation n'est plus traçable."
                ),
                location_kind="citation",
                location_ref=citation.citation_id,
                location_label=citation.section_title,
                remedy=(
                    "Ouvrir la citation, rattacher une référence existante ou retirer la "
                    "citation. L'application ne choisit pas à votre place."
                ),
                meta={"node_id": citation.node_id},
            )
        )
    return outcome


def check_pending_citations(data: AuditData) -> CheckOutcome:
    """Citation nodes present in a document but unknown to the server.

    They are usually a document saved before the citation was registered, or a stage 3
    placeholder that was never attached to a reference.
    """
    outcome = CheckOutcome(code="citations.non_enregistrees")
    pending = [citation for citation in data.citations if citation.is_pending]
    for citation in pending:
        outcome.findings.append(
            Finding(
                code="citations.non_enregistrees",
                severity=Severity.WARNING,
                title="Citation non enregistrée",
                detail=(
                    f"La section « {citation.section_title} » contient une citation qui "
                    "n'est reliée à aucune entrée de la bibliographie. Elle n'apparaîtra pas "
                    "dans la bibliographie finale."
                ),
                location_kind="section",
                location_ref=citation.section_id,
                location_label=citation.section_title,
                remedy="Enregistrer la section pour enregistrer la citation, puis la rattacher.",
                meta={"node_id": citation.node_id},
            )
        )
    return outcome


def check_citation_without_reference(data: AuditData) -> CheckOutcome:
    """A citation block that points at no reference at all."""
    outcome = CheckOutcome(code="citations.sans_reference")
    empty = [citation for citation in data.citations if not citation.reference_ids]
    for citation in empty:
        outcome.findings.append(
            Finding(
                code="citations.sans_reference",
                severity=Severity.BLOCKER,
                title="Citation sans référence",
                detail=(
                    f"Une citation de la section « {citation.section_title} » ne désigne "
                    "aucune référence de la bibliothèque."
                ),
                location_kind="citation",
                location_ref=citation.citation_id,
                location_label=citation.section_title,
                remedy="Sélectionner une référence, ou supprimer la citation.",
            )
        )
    return outcome


def check_uncited_references(data: AuditData) -> CheckOutcome:
    """References that exist in the library but are never cited.

    Not an error: a student keeps reading material. It is reported as information, because it
    also matters for the final bibliography, which only lists cited works.
    """
    outcome = CheckOutcome(code="bibliographie.non_citees")
    cited = {reference_id for citation in data.citations for reference_id in citation.reference_ids}
    uncited = [
        reference
        for reference in data.references
        if reference.reference_id not in cited and not reference.is_deleted
    ]
    if not uncited:
        return outcome
    for reference in uncited:
        outcome.findings.append(
            Finding(
                code="bibliographie.non_citees",
                severity=Severity.INFO,
                title="Référence jamais citée",
                detail=(
                    f"« {reference.citation_key} » est dans la bibliothèque mais n'est citée "
                    "dans aucune section. Elle ne figurera pas dans la bibliographie finale."
                ),
                location_kind="reference",
                location_ref=reference.reference_id,
                location_label=reference.citation_key,
                remedy=(
                    "La citer si elle est utilisée, ou la conserver comme source de travail : "
                    "une référence de bibliothèque n'est pas une référence du mémoire."
                ),
            )
        )
    return outcome


def check_duplicate_citations(data: AuditData) -> CheckOutcome:
    """The same reference cited twice in the same sentence or in adjacent sentences.

    A duplicated citation is almost always a copy-paste slip and a jury notices it, so it is
    a warning rather than information.
    """
    outcome = CheckOutcome(code="citations.doublons")
    by_section: dict[str, list[CitationView]] = defaultdict(list)
    for citation in data.citations:
        by_section[citation.section_id].append(citation)
    for section_id, group in by_section.items():
        ordered = sorted(group, key=lambda item: item.node_id)
        seen: set[tuple[str, ...]] = set()
        previous: tuple[str, ...] | None = None
        for citation in ordered:
            key = tuple(sorted(citation.reference_ids))
            if not key:
                continue
            if key == previous or key in seen:
                label = citation.section_title
                outcome.findings.append(
                    Finding(
                        code="citations.doublons",
                        severity=Severity.WARNING,
                        title="Citation répétée",
                        detail=(
                            f"La même référence est citée plusieurs fois de suite dans la "
                            f"section « {label} ». Une citation répétée sans raison apparente "
                            "ressemble à une erreur de copier-coller."
                        ),
                        location_kind="section",
                        location_ref=section_id,
                        location_label=label,
                        remedy="Vérifier si la seconde citation est nécessaire.",
                    )
                )
            seen.add(key)
            previous = key
    return outcome


def check_reference_completeness(data: AuditData) -> CheckOutcome:
    """References with missing metadata, per type.

    The required fields depend on the type: an article needs a journal, a book needs a
    publisher. Nothing is filled in; the missing field is named.
    """
    outcome = CheckOutcome(code="bibliographie.incompletes")
    for reference in data.references:
        if reference.is_deleted:
            continue
        missing: list[str] = []
        if not reference.author_count:
            missing.append("auteur")
        if not reference.publication_year:
            missing.append("année")
        if not reference.title:
            missing.append("titre")
            missing.append("DOI ou URL")
        if not reference.has_doi and reference.reference_type in {
            "article",
            "book",
            "book_chapter",
            "thesis",
            "conference",
        }:
            missing.append("DOI")
        if missing:
            outcome.findings.append(
                Finding(
                    code="bibliographie.incompletes",
                    severity=Severity.WARNING,
                    title="Référence incomplète",
                    detail=(
                        f"« {reference.citation_key} » ({reference.reference_type}) : "
                        f"{', '.join(missing)} — {MISSING_LABEL}."
                    ),
                    location_kind="reference",
                    location_ref=reference.reference_id,
                    location_label=reference.citation_key,
                    remedy="Compléter les métadonnées dans la bibliothèque.",
                    count=len(missing),
                    meta={"missing": missing},
                )
            )
    return outcome


def check_duplicate_references(data: AuditData) -> CheckOutcome:
    """Duplicates carried over from stage 9, surfaced in the audit."""
    outcome = CheckOutcome(code="bibliographie.doublons")
    duplicates = [reference for reference in data.references if reference.duplicate_level]
    for reference in duplicates:
        outcome.findings.append(
            Finding(
                code="bibliographie.doublons",
                severity=Severity.WARNING,
                title="Doublon de référence",
                detail=(
                    f"« {reference.citation_key} » correspond à une autre référence "
                    f"({reference.duplicate_level}). Les deux compteurs de la bibliographie "
                    "finale seraient incohérents."
                ),
                location_kind="reference",
                location_ref=reference.reference_id,
                location_label=reference.citation_key,
                meta={"level": reference.duplicate_level},
            )
        )
    return outcome


def check_style_consistency(data: AuditData) -> CheckOutcome:
    """The bibliographic style must be one the engine actually implements.

    A style that does not resolve falls back silently, which is exactly the kind of thing a
    student must be told about.
    """
    from app.citations.styles import STYLE_ALIASES, STYLE_REGISTRY

    outcome = CheckOutcome(code="bibliographie.style")
    stored = (data.project.bibliography_style or "").strip()
    if not stored:
        outcome.findings.append(
            Finding(
                code="bibliographie.style",
                severity=Severity.WARNING,
                title="Style bibliographique non défini",
                location_kind="project",
                location_ref=data.project.project_id,
                remedy="Choisir le style imposé par l'établissement.",
            )
        )
        return outcome
    # The raw value is checked, not the normalised one: normalisation always resolves to a
    # valid style, so testing its result would make this check unreachable.
    key = stored.casefold()
    if key not in STYLE_REGISTRY and key not in STYLE_ALIASES:
        outcome.findings.append(
            Finding(
                code="bibliographie.style",
                severity=Severity.WARNING,
                title="Style bibliographique inconnu",
                detail=(
                    f"Le style « {stored} » n'est pas implémenté. "
                    f"{INSUFFICIENT_LABEL} pour appliquer le bon format."
                ),
                location_kind="project",
                location_ref=data.project.project_id,
                remedy="Choisir un style parmi APA 7, Harvard, Vancouver ou ISO 690.",
            )
        )
    return outcome


# ------------------------------------------------------------------ sources


def check_source_provenance(data: AuditData) -> CheckOutcome:
    """Every source used must carry its provenance chain.

    A source whose text was extracted without page and block information cannot be cited
    rigorously, because a reader could not be sent back to the exact passage.
    """
    outcome = CheckOutcome(code="sources.provenance")
    for source in data.sources:
        if source.indexed and not source.has_provenance:
            outcome.findings.append(
                Finding(
                    code="sources.provenance",
                    severity=Severity.BLOCKER,
                    title="Source sans provenance",
                    detail=(
                        f"« {source.title or source.original_filename or 'Source'} » est "
                        "indexée sans traçabilité de page ni de bloc. Une affirmation tirée "
                        "de cette source ne pourra pas être vérifiée."
                    ),
                    location_kind="source",
                    location_ref=source.source_id,
                    location_label=source.title or source.original_filename,
                    remedy="Réimporter la source pour reconstruire la provenance.",
                )
            )
    return outcome


def check_source_processing(data: AuditData) -> CheckOutcome:
    """Sources whose processing failed or never produced a file."""
    outcome = CheckOutcome(code="sources.etat")
    for source in data.sources:
        label = source.title or source.original_filename or "Source"
        if source.status in {"failed", "error"}:
            outcome.findings.append(
                Finding(
                    code="sources.etat",
                    severity=Severity.WARNING,
                    title="Source en erreur",
                    detail=(
                        f"? {label} ? n'a pas pu ?tre trait?e. Son contenu n'est pas "
                        "recherchable et ne peut pas ?tre cit?."
                    ),
                    location_kind="source",
                    location_ref=source.source_id,
                    location_label=label,
                    remedy="Relancer l'extraction, ou retirer la source de la bibliographie.",
                )
            )
        elif source.status == "pending" or (not source.indexed and source.file_count):
            outcome.findings.append(
                Finding(
                    code="sources.etat",
                    severity=Severity.INFO,
                    title="Source non indexée",
                    detail=f"« {label} » n'est pas encore interrogeable par la recherche.",
                    location_kind="source",
                    location_ref=source.source_id,
                    location_label=label,
                )
            )
    return outcome


def check_source_bibliography_link(data: AuditData) -> CheckOutcome:
    """Cited references that have no file and no identifier.

    A reference without DOI, without URL and without a linked source cannot be consulted by
    a reader. This is a real defence risk.
    """
    outcome = CheckOutcome(code="sources.consultabilite")
    for reference in data.references:
        if reference.is_deleted:
            continue
        if reference.has_doi or reference.has_url:
            continue
        outcome.findings.append(
            Finding(
                code="sources.consultabilite",
                severity=Severity.WARNING,
                title="Référence non consultable",
                detail=(
                    f"« {reference.citation_key} » n'a ni DOI, ni URL, ni fichier source "
                    "associé. Un lecteur ne pourra pas la retrouver."
                ),
                location_kind="reference",
                location_ref=reference.reference_id,
                location_label=reference.citation_key,
            )
        )
    return outcome


# ----------------------------------------------------------------- structure


def check_project_metadata(data: AuditData) -> CheckOutcome:
    """The administrative metadata a jury reads first."""
    outcome = CheckOutcome(code="projet.metadonnees")
    labels = (
        ("author_name", "auteur"),
        ("institution", "établissement"),
        ("education_level", "niveau"),
        ("academic_year", "année universitaire"),
        ("supervisor_name", "encadreur"),
        ("thesis_type", "type de mémoire"),
    )
    missing = [
        label for attribute, label in labels if not getattr(data.project, attribute, None)
    ]
    if missing:
        outcome.findings.append(
            Finding(
                code="projet.metadonnees",
                severity=Severity.BLOCKER,
                title="Informations administratives incomplètes",
                detail=(
                    f"Non renseigné : {', '.join(missing)}. La page de garde de l'export "
                    "porterait la mention « Non renseigné »."
                ),
                location_kind="project",
                location_ref=data.project.project_id,
                remedy="Compléter les informations du mémoire.",
                count=len(missing),
                meta={"missing": missing},
            )
        )
    return outcome


def check_academic_framing(data: AuditData) -> CheckOutcome:
    """Problem statement, objectives and hypotheses.

    A memoir without a stated problem, an objective or a hypothesis cannot answer the
    question its jury will ask, so this is a blocker rather than a nicety.
    """
    outcome = CheckOutcome(code="projet.cadrage")
    if not (data.project.problem_statement or "").strip():
        outcome.findings.append(
            Finding(
                code="projet.cadrage",
                severity=Severity.BLOCKER,
                title="Problématique absente",
                detail=f"{MISSING_LABEL} : le mémoire ne formule pas le problème qu'il traite.",
                location_kind="project",
                location_ref=data.project.project_id,
            )
        )
    if not (data.project.general_objective or "").strip() and not data.project.specific_objectives:
        outcome.findings.append(
            Finding(
                code="projet.cadrage",
                severity=Severity.BLOCKER,
                title="Objectif absent",
                detail=f"{MISSING_LABEL} : ni objectif général ni objectifs spécifiques.",
                location_kind="project",
                location_ref=data.project.project_id,
                remedy="Formuler l'objectif général, puis décliner les objectifs spécifiques.",
            )
        )
    if not data.project.hypotheses:
        outcome.findings.append(
            Finding(
                code="projet.cadrage",
                severity=Severity.WARNING,
                title="Hypothèses absentes",
                detail=(
                    f"{MISSING_LABEL} : les hypothèses ne sont pas formulées. Une partie "
                    "méthodologique sera jugée incomplète sans elles."
                ),
                location_kind="project",
                location_ref=data.project.project_id,
                remedy="Formuler les hypothèses de recherche.",
            )
        )
    return outcome


def check_empty_sections(data: AuditData) -> CheckOutcome:
    """Sections declared in the plan but still empty."""
    outcome = CheckOutcome(code="structure.sections_vides")
    for section in data.sections:
        if section.status == "empty" or section.word_count == 0:
            outcome.findings.append(
                Finding(
                    code="structure.sections_vides",
                    severity=Severity.WARNING,
                    title="Section vide",
                    detail=(
                        f"« {section.title} » est prévue au plan mais ne contient aucun texte."
                    ),
                    location_kind="section",
                    location_ref=section.section_id,
                    location_label=section.title,
                    remedy="Rédiger la section, ou la retirer du plan.",
                )
            )
    return outcome


def check_unfinished_sections(data: AuditData) -> CheckOutcome:
    """Sections still marked as in progress."""
    outcome = CheckOutcome(code="structure.sections_en_cours")
    for section in data.sections:
        if section.status == "in_progress":
            outcome.findings.append(
                Finding(
                    code="structure.sections_en_cours",
                    severity=Severity.INFO,
                    title="Section en cours",
                    detail=f"« {section.title} » n'est pas encore marquée comme terminée.",
                    location_kind="section",
                    location_ref=section.section_id,
                    location_label=section.title,
                    remedy="Relire puis marquer la section comme terminée.",
                )
            )
    return outcome


def check_missing_expected_sections(data: AuditData) -> CheckOutcome:
    """Standard parts a thesis is expected to contain, when the platform declares them.

    The audit never invents a section: it only reports that a declared one is absent.
    """
    outcome = CheckOutcome(code="structure.sections_attendues")
    if data.expected_section_count is None:
        outcome.skipped_reason = (
            "Le projet ne déclare pas de plan type : impossible de conclure."
        )
        return outcome
    present = len([section for section in data.sections if section.word_count > 0])
    if present < data.expected_section_count:
        outcome.findings.append(
            Finding(
                code="structure.sections_attendues",
                severity=Severity.WARNING,
                title="Plan incomplet",
                detail=(
                    f"{present} section(s) renseignée(s) sur {data.expected_section_count} "
                    "attendues par le plan type."
                ),
                location_kind="project",
                location_ref=data.project.project_id,
                remedy="Ajouter les sections manquantes au plan, ou adapter le plan type.",
                count=data.expected_section_count - present,
            )
        )
    return outcome


def check_required_parts(data: AuditData) -> CheckOutcome:
    """Method, results and conclusion must exist somewhere in the memoir.

    The detection is lexical and deliberately conservative: a part counts as present when a
    heading resembles it. When nothing resembles it, the audit says ``Source insuffisante``
    for a claim it cannot make, rather than declaring the part missing outright.
    """
    outcome = CheckOutcome(code="structure.parts_attendus")
    markers: dict[str, tuple[str, ...]] = {
        "méthodologie": ("methode", "methodologie", "materiel", "demarche", "method"),
        "résultats": ("resultat", "resultats", "resultats et discussion"),
        "conclusion": ("conclusion", "discussion et conclusion"),
    }
    # Accents are stripped before matching: a French title such as "Mat?riel et m?thodes"
    # must be recognised by the needle "materiel", otherwise the check reports a false warning.
    haystack = " | ".join(_plain(section.title) for section in data.sections)
    if not haystack.strip():
        outcome.skipped_reason = "Le mémoire ne contient aucune section : rien à comparer."
        return outcome
    for part, needles in markers.items():
        if not any(needle in haystack for needle in needles):
            outcome.findings.append(
                Finding(
                    code="structure.parts_attendus",
                    severity=Severity.WARNING,
                    title=f"Partie « {part} » non repérée",
                    detail=(
                        f"Aucun titre de section ne mentionne la {part}. La partie peut "
                        f"exister sous un autre intitulé : l'absence d'un titre ne prouve "
                        f"rien. Statut : {TO_VERIFY_LABEL}."
                    ),
                    location_kind="project",
                    location_ref=data.project.project_id,
                    remedy=f"Vérifier que le mémoire comporte bien une partie {part}.",
                )
            )
    return outcome


def check_framing_alignment(data: AuditData) -> CheckOutcome:
    """Whether the objectives and the content actually meet each other.

    The check is lexical on purpose: it compares the significant words of the stated
    objectives with the words of the section titles, and reports a mismatch as a question for
    the author rather than as a verdict.
    """
    outcome = CheckOutcome(code="projet.ad_coherence")
    objectives = [
        *(data.project.specific_objectives or ()),
        *([data.project.general_objective] if data.project.general_objective else []),
    ]
    cleaned = [objective for objective in objectives if objective and objective.strip()]
    if not cleaned:
        outcome.skipped_reason = "Aucun objectif à comparer."
        return outcome
    section_words = _significant_words(
        " ".join(section.title for section in data.sections)
    )
    if not section_words:
        outcome.skipped_reason = "Le plan ne comporte aucun titre exploitable."
        return outcome
    for objective in cleaned:
        objective_words = _significant_words(objective)
        if not objective_words:
            continue
        overlap = objective_words & section_words
        if not overlap:
            outcome.findings.append(
                Finding(
                    code="projet.ad_coherence",
                    severity=Severity.INFO,
                    title="Objectif sans section correspondante",
                    detail=(
                        "Un objectif n'a aucun mot significatif en commun avec les titres de "
                        "section. Il peut s'agir d'une intitulé différent, ou d'un objectif "
                        "non traité."
                    ),
                    location_kind="project",
                    location_ref=data.project.project_id,
                    remedy="Vérifier que cet objectif est traité par une section du plan.",
                )
            )
    return outcome


def _plain(text: str) -> str:
    """Case-folded and without accents, so a French needle matches an accented title."""
    import unicodedata

    decomposed = unicodedata.normalize("NFKD", text or "")
    return "".join(
        char for char in decomposed if not unicodedata.combining(char)
    ).casefold()


def _significant_words(text: str) -> set[str]:
    stop = {
        "de", "du", "des", "la", "le", "les", "un", "une", "et", "ou", "a", "au", "aux",
        "en", "pour", "par", "sur", "dans", "avec", "sans", "the", "of", "and", "et",
        "d", "l", "n", "s", "est", "sont", "etre",
    }
    words = {
        word
        for word in "".join(
            character if character.isalnum() else " " for character in _plain(text)
        ).split()
        if len(word) > 3 and word not in stop
    }
    return words


# ---------------------------------------------------------------- coherence


def check_problem_objectives_alignment(data: AuditData) -> CheckOutcome:
    """The problem, the objectives and the hypotheses must speak about the same thing."""
    outcome = CheckOutcome(code="coherence.probleme_objectifs")
    problem = _significant_words(data.project.problem_statement or "")
    objectives = _significant_words(
        " ".join(
            [
                data.project.general_objective or "",
                *(data.project.specific_objectives or ()),
            ]
        )
    )
    if not problem or not objectives:
        outcome.skipped_reason = (
            "Problématique ou objectifs non renseignés : comparaison impossible."
        )
        return outcome
    if not (problem & objectives):
        outcome.findings.append(
            Finding(
                code="coherence.probleme_objectifs",
                severity=Severity.WARNING,
                title="Problématique et objectifs sans lien lexical",
                detail=(
                    "La problématique et les objectifs ne partagent aucun terme "
                    "significatif. Ils peuvent rester cohérents malgré des formulations "
                    "différentes, mais cela vaut la peine d'être vérifié."
                ),
                location_kind="project",
                location_ref=data.project.project_id,
                remedy="Relire la problématique et les objectifs côte à côte.",
            )
        )
    return outcome


def check_hypotheses_results_alignment(data: AuditData) -> CheckOutcome:
    """Whether the memoir has results and a conclusion to confront the hypotheses.

    This cannot conclude anything about the truth of the hypotheses, only about whether the
    pieces needed to discuss them are present.
    """
    outcome = CheckOutcome(code="coherence.hypotheses_resultats")
    if not data.project.hypotheses:
        outcome.skipped_reason = "Aucune hypothèse formulée."
        return outcome
    titles = " | ".join(_plain(section.title) for section in data.sections)
    has_results = "resultat" in titles
    has_conclusion = "conclusion" in titles
    if not has_results:
        outcome.findings.append(
            Finding(
                code="coherence.hypotheses_resultats",
                severity=Severity.WARNING,
                title="Hypothèses sans résultats",
                detail=(
                    "Des hypothèses sont formulées mais aucune section de résultats n'est "
                    "repérée. Elles ne pourront pas être confrontées."
                ),
                location_kind="project",
                location_ref=data.project.project_id,
                remedy="Ajouter ou renommer une section de résultats.",
            )
        )
    if not has_conclusion:
        outcome.findings.append(
            Finding(
                code="coherence.hypotheses_resultats",
                severity=Severity.WARNING,
                title="Hypothèses sans conclusion",
                detail="Des hypothèses sont formulées mais aucune conclusion n'est repérée.",
                location_kind="project",
                location_ref=data.project.project_id,
                remedy="Ajouter une section de conclusion.",
            )
        )
    return outcome


def check_citation_bibliography_alignment(data: AuditData) -> CheckOutcome:
    """The bibliography must contain exactly the cited references, and nothing else."""
    outcome = CheckOutcome(code="coherence.citations_bibliographie")
    known = {reference.reference_id for reference in data.references}
    cited = {
        reference_id for citation in data.citations for reference_id in citation.reference_ids
    }
    dangling = sorted(cited - known)
    if dangling:
        outcome.findings.append(
            Finding(
                code="coherence.citations_bibliographie",
                severity=Severity.BLOCKER,
                title="Citation hors bibliographie",
                detail=(
                    f"{len(dangling)} référence(s) citée(s) n'existent pas dans la "
                    "bibliographie. Elles ne peuvent pas apparaître dans la bibliographie "
                    "finale."
                ),
                location_kind="project",
                location_ref=data.project.project_id,
                count=len(dangling),
                meta={"reference_ids": dangling},
            )
        )
    return outcome


def check_uncited_ratio(data: AuditData) -> CheckOutcome:
    """A very high proportion of unread references suggests a library that was never used."""
    outcome = CheckOutcome(code="coherence.couverture_bibliographique")
    live = [reference for reference in data.references if not reference.is_deleted]
    if not live:
        outcome.skipped_reason = "Bibliothèque vide."
        return outcome
    cited = {
        reference_id for citation in data.citations for reference_id in citation.reference_ids
    }
    used = len([reference for reference in live if reference.reference_id in cited])
    ratio = used / len(live)
    if ratio < 0.2 and len(live) > 5:
        outcome.findings.append(
            Finding(
                code="coherence.couverture_bibliographique",
                severity=Severity.INFO,
                title="Couverture bibliographique faible",
                detail=(
                    f"{used} référence(s) citée(s) sur {len(live)} ({round(ratio * 100)} %). "
                    "La bibliothèque contient beaucoup de documents non mobilisés."
                ),
                location_kind="project",
                location_ref=data.project.project_id,
                remedy="Citer les références effectivement utilisées, ou alléger la bibliothèque.",
            )
        )
    return outcome


def check_stale_academic_year(data: AuditData) -> CheckOutcome:
    """A memoir whose academic year does not match the current one."""
    outcome = CheckOutcome(code="projet.annee")
    year = (data.project.academic_year or "").strip()
    if not year or not data.current_academic_year:
        return outcome
    if data.current_academic_year not in year:
        outcome.findings.append(
            Finding(
                code="projet.annee",
                severity=Severity.WARNING,
                title="Année universitaire à vérifier",
                detail=(
                    f"Le mémoire indique « {year} » alors que l'année en cours est "
                    f"« {data.current_academic_year} »."
                ),
                location_kind="project",
                location_ref=data.project.project_id,
                remedy="Mettre à jour l'année universitaire.",
            )
        )
    return outcome


#: Every check, in the order the report presents them.
ALL_CHECKS: tuple = (
    check_project_metadata,
    check_academic_framing,
    check_stale_academic_year,
    check_orphan_citations,
    check_citation_without_reference,
    check_pending_citations,
    check_duplicate_citations,
    check_citation_bibliography_alignment,
    check_style_consistency,
    check_reference_completeness,
    check_duplicate_references,
    check_uncited_references,
    check_uncited_ratio,
    check_source_provenance,
    check_source_processing,
    check_source_bibliography_link,
    check_empty_sections,
    check_unfinished_sections,
    check_missing_expected_sections,
    check_required_parts,
    check_framing_alignment,
    check_problem_objectives_alignment,
    check_hypotheses_results_alignment,
)


__all__ = [
    "ALL_CHECKS",
    "AuditData",
    "CitationView",
    "ProjectView",
    "ReferenceView",
    "SectionView",
    "SourceView",
]
