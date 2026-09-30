"""Tests of the academic audit.

The audit is a pure function of the collected data, so the whole module is testable without a
database. These tests pin the behaviours a student depends on:

* a missing value is reported as missing, never replaced;
* a doubtful citation is reported as doubtful, never dressed up with a plausible author;
* a check that cannot conclude says so instead of looking like a pass;
* the audit is deterministic and never calls a language model.
"""

from __future__ import annotations

import inspect
from uuid import uuid4

import pytest

from app.audit import checks, service
from app.audit.checks import (
    ALL_CHECKS,
    AuditData,
    CitationView,
    ProjectView,
    ReferenceView,
    SectionView,
    SourceView,
)
from app.audit.findings import (
    INSUFFICIENT_LABEL,
    MISSING_LABEL,
    TO_VERIFY_LABEL,
    Finding,
    Severity,
)
from app.audit.service import build_audit_report, build_defence_checklist, run_checks
from app.audit.statistics import compute_stats, volume_observations

# ------------------------------------------------------------------ fixtures


def project(**overrides) -> ProjectView:
    defaults = {
        "project_id": str(uuid4()),
        "title": "Composition du grain de jacquier",
        "author_name": "Rakoto Marie",
        "institution": "Université",
        "education_level": "master",
        "academic_year": "2025-2026",
        "supervisor_name": "Pr. Dupont",
        "thesis_type": "Mémoire",
        "problem_statement": "Quelle est la composition du grain de jacquier ?",
        "general_objective": "Caractériser la farine de jacquier.",
        "specific_objectives": ("Doser les protéines.", "Mesurer la capacité émulsifiante."),
        "hypotheses": ("La farine améliore l'émulsion.",),
        "keywords": ("jacquier",),
        "bibliography_style": "apa7",
    }
    defaults.update(overrides)
    return ProjectView(**defaults)  # type: ignore[arg-type]


def section(
    title: str = "Introduction",
    level: int = 1,
    words: int = 1200,
    status: str = "complete",
    citations: int = 3,
    figures: int = 1,
    tables: int = 0,
    equations: int = 0,
) -> SectionView:
    return SectionView(
        section_id=str(uuid4()),
        title=title,
        level=level,
        word_count=words,
        status=status,
        plain_text="mot " * words,
        citation_count=citations,
        figure_count=figures,
        table_count=tables,
        equation_count=equations,
    )


def reference(
    key: str = "dupont2024",
    *,
    reference_type: str = "article",
    title: str | None = "Composition",
    year: int | None = 2024,
    authors: int = 1,
    doi: bool = True,
    url: bool = False,
    deleted: bool = False,
    duplicate: str | None = None,
) -> ReferenceView:
    return ReferenceView(
        reference_id=str(uuid4()),
        citation_key=key,
        reference_type=reference_type,
        title=title,
        publication_year=year,
        author_count=authors,
        organisation_count=0,
        has_doi=doi,
        has_url=url,
        has_abstract=False,
        keyword_count=2,
        is_deleted=deleted,
        duplicate_level=duplicate,
    )


def citation(
    *reference_ids: str,
    orphaned: bool = False,
    pending: bool = False,
    section_title: str = "Introduction",
    mode: str = "parenthetical",
    text: str = "(Dupont, 2024)",
) -> CitationView:
    return CitationView(
        citation_id=str(uuid4()),
        section_id=str(uuid4()),
        section_title=section_title,
        node_id=f"cit-{uuid4().hex[:8]}",
        rendered_text=text,
        is_orphaned=orphaned,
        is_pending=pending,
        mode=mode,
        reference_ids=tuple(reference_ids),
    )


def source(**overrides) -> SourceView:
    defaults = {
        "source_id": str(uuid4()),
        "title": "Article jacquier",
        "original_filename": "article.pdf",
        "status": "indexed",
        "file_count": 1,
        "page_count": 12,
        "block_count": 40,
        "indexed": True,
        "has_provenance": True,
    }
    defaults.update(overrides)
    return SourceView(**defaults)  # type: ignore[arg-type]


def data(**overrides) -> AuditData:
    defaults = {
        "project": project(),
        "sections": [section()],
        "references": [],
        "citations": [],
        "sources": [],
    }
    defaults.update(overrides)
    return AuditData(**defaults)  # type: ignore[arg-type]


# ------------------------------------------------------------- finding model


def test_a_finding_carries_a_location_and_a_remedy() -> None:
    finding = Finding(
        code="x",
        severity=Severity.WARNING,
        title="Titre",
        detail="Détail",
        remedy="Action",
        location_kind="section",
        location_ref="abc",
        location_label="Introduction",
    )
    payload = finding.as_dict()
    assert payload["remedy"] == "Action"
    assert payload["location_ref"] == "abc"
    assert payload["severity_label"] == "À vérifier"


def test_severities_are_ordered_blocker_first() -> None:
    assert Severity.BLOCKER.rank < Severity.WARNING.rank < Severity.INFO.rank


def test_the_three_missing_data_labels_exist() -> None:
    assert MISSING_LABEL == "Non renseigné"
    assert INSUFFICIENT_LABEL == "Source insuffisante"
    assert TO_VERIFY_LABEL == "À vérifier"


# ------------------------------------------------------------------ orphans


def test_an_orphan_citation_is_a_blocker() -> None:
    outcome = checks.check_orphan_citations(
        data(citations=[citation(orphaned=True, text="[Citation invalide]")])
    )
    assert outcome.findings
    assert outcome.findings[0].severity == Severity.BLOCKER
    assert "référence supprimée" in outcome.findings[0].detail


def test_a_valid_citation_produces_no_orphan_finding() -> None:
    assert checks.check_orphan_citations(data(citations=[citation()])).findings == []


def test_a_citation_without_any_reference_is_a_blocker() -> None:
    outcome = checks.check_citation_without_reference(data(citations=[citation()]))
    assert outcome.findings
    assert outcome.findings[0].severity == Severity.BLOCKER


def test_a_pending_citation_is_a_warning_not_a_silent_pass() -> None:
    outcome = checks.check_pending_citations(data(citations=[citation(pending=True)]))
    assert outcome.findings
    assert outcome.findings[0].severity == Severity.WARNING


# ------------------------------------------------------------------ uncited


def test_an_uncited_reference_is_reported_as_information_only() -> None:
    ref = reference()
    outcome = checks.check_uncited_references(
        data(references=[ref], citations=[citation()])
    )
    assert outcome.findings
    assert outcome.findings[0].severity == Severity.INFO
    assert "bibliographie finale" in outcome.findings[0].detail


def test_a_cited_reference_is_not_reported_as_uncited() -> None:
    ref = reference()
    outcome = checks.check_uncited_references(
        data(references=[ref], citations=[citation(ref.reference_id)])
    )
    assert outcome.findings == []


def test_a_deleted_reference_is_not_counted_as_uncited() -> None:
    outcome = checks.check_uncited_references(
        data(references=[reference(deleted=True)], citations=[])
    )
    assert outcome.findings == []


# ---------------------------------------------------------- duplicate cites


def test_two_identical_adjacent_citations_are_reported() -> None:
    first = citation("ref-1")
    second = citation("ref-1")
    second.section_id = first.section_id
    outcome = checks.check_duplicate_citations(data(citations=[first, second]))
    assert outcome.findings
    assert outcome.findings[0].severity == Severity.WARNING
    assert "copier-coller" in outcome.findings[0].detail


def test_two_different_citations_are_not_duplicates() -> None:
    first = citation("ref-1")
    second = citation("ref-2")
    second.section_id = first.section_id
    assert checks.check_duplicate_citations(data(citations=[first, second])).findings == []


def test_a_multi_reference_citation_is_compared_as_a_whole() -> None:
    first = citation("a", "b")
    second = citation("a", "b")
    second.section_id = first.section_id
    assert checks.check_duplicate_citations(data(citations=[first, second])).findings


# ------------------------------------------------------------- completeness


def test_a_reference_without_author_or_year_is_reported_as_missing() -> None:
    outcome = checks.check_reference_completeness(
        data(references=[reference(authors=0, year=None)])
    )
    assert outcome.findings
    detail = outcome.findings[0].detail
    assert "auteur" in detail
    assert "année" in detail
    assert MISSING_LABEL in detail


def test_a_complete_reference_produces_no_finding() -> None:
    assert checks.check_reference_completeness(data(references=[reference()])).findings == []


def test_a_consultable_reference_is_not_reported() -> None:
    outcome = checks.check_source_bibliography_link(
        data(references=[reference(doi=True, url=True)])
    )
    assert outcome.findings == []


def test_a_reference_without_doi_nor_url_nor_file_is_reported() -> None:
    outcome = checks.check_source_bibliography_link(
        data(references=[reference(doi=False, url=False)])
    )
    assert outcome.findings
    assert "non consultable" in outcome.findings[0].title


# ----------------------------------------------------------------- sources


def test_an_indexed_source_without_provenance_is_a_blocker() -> None:
    outcome = checks.check_source_provenance(
        data(sources=[source(has_provenance=False, page_count=0, block_count=0)])
    )
    assert outcome.findings
    assert outcome.findings[0].severity == Severity.BLOCKER


def test_a_source_with_provenance_is_accepted() -> None:
    assert checks.check_source_provenance(data(sources=[source()])).findings == []


def test_a_failed_source_is_reported() -> None:
    outcome = checks.check_source_processing(data(sources=[source(status="failed")]))
    assert outcome.findings
    assert outcome.findings[0].title == "Source en erreur"


# ------------------------------------------------------------------ project


def test_missing_administrative_metadata_is_a_blocker() -> None:
    outcome = checks.check_project_metadata(
        data(project=project(author_name=None, institution=None, supervisor_name=None))
    )
    assert outcome.findings
    assert outcome.findings[0].severity == Severity.BLOCKER
    assert MISSING_LABEL in outcome.findings[0].detail


def test_a_complete_project_has_no_metadata_finding() -> None:
    assert checks.check_project_metadata(data()).findings == []


def test_a_missing_problem_statement_is_a_blocker() -> None:
    outcome = checks.check_academic_framing(
        data(project=project(problem_statement=None, hypotheses=()))
    )
    codes = {finding.code for finding in outcome.findings}
    assert outcome.findings
    assert any("Problématique" in finding.title for finding in outcome.findings)
    assert codes


def test_a_missing_hypothesis_is_only_a_warning() -> None:
    outcome = checks.check_academic_framing(data(project=project(hypotheses=())))
    hypotheses = [
        finding for finding in outcome.findings if finding.title == "Hypothèses absentes"
    ]
    assert hypotheses and hypotheses[0].severity == Severity.WARNING


def test_an_unknown_bibliography_style_is_reported() -> None:
    outcome = checks.check_style_consistency(
        data(project=project(bibliography_style="purdeun"))
    )
    assert outcome.findings
    assert "inconnu" in outcome.findings[0].title


def test_a_known_style_produces_no_finding() -> None:
    assert checks.check_style_consistency(data()).findings == []


def test_a_legacy_style_value_is_accepted() -> None:
    assert checks.check_style_consistency(
        data(project=project(bibliography_style="apa"))
    ).findings == []


def test_a_stale_academic_year_is_reported() -> None:
    outcome = checks.check_stale_academic_year(
        data(project=project(academic_year="2019-2020"), current_academic_year="2025-2026")
    )
    assert outcome.findings
    assert "2019-2020" in outcome.findings[0].detail


def test_a_current_academic_year_is_accepted() -> None:
    assert checks.check_stale_academic_year(
        data(current_academic_year="2025-2026")
    ).findings == []


# ---------------------------------------------------------------- structure


def test_an_empty_section_is_reported() -> None:
    outcome = checks.check_empty_sections(data(sections=[section(words=0, status="empty")]))
    assert outcome.findings
    assert outcome.findings[0].location_kind == "section"


def test_a_section_in_progress_is_information_only() -> None:
    outcome = checks.check_unfinished_sections(
        data(sections=[section(status="in_progress")])
    )
    assert outcome.findings
    assert outcome.findings[0].severity == Severity.INFO


def test_a_check_without_a_plan_type_is_inconclusive_not_passing() -> None:
    outcome = checks.check_missing_expected_sections(data(expected_section_count=None))
    assert outcome.findings == []
    assert outcome.skipped_reason
    assert "conclure" in outcome.skipped_reason


def test_a_complete_plan_produces_no_structure_finding() -> None:
    assert checks.check_missing_expected_sections(data(expected_section_count=1)).findings == []


def test_an_incomplete_plan_is_reported() -> None:
    outcome = checks.check_missing_expected_sections(data(expected_section_count=5))
    assert outcome.findings
    assert outcome.findings[0].count == 4


def test_a_missing_methods_part_is_reported_without_proving_anything() -> None:
    outcome = checks.check_required_parts(
        data(sections=[section(title="Introduction"), section(title="Conclusion")])
    )
    titles = " ".join(finding.title for finding in outcome.findings)
    assert "méthodologie" in titles
    assert "résultats" in titles
    # The message must not pretend the part is definitely absent.
    assert any("ne prouve rien" in finding.detail for finding in outcome.findings)


def test_a_plan_with_methods_results_and_conclusion_is_accepted() -> None:
    outcome = checks.check_required_parts(
        data(
            sections=[
                section(title="Introduction"),
                section(title="Matériel et méthodes"),
                section(title="Résultats"),
                section(title="Conclusion"),
            ]
        )
    )
    assert outcome.findings == []


def test_required_parts_is_inconclusive_on_an_empty_plan() -> None:
    outcome = checks.check_required_parts(data(sections=[]))
    assert outcome.skipped_reason
    assert outcome.findings == []


# ---------------------------------------------------------------- coherence


def test_problem_and_objectives_sharing_no_word_is_reported() -> None:
    outcome = checks.check_problem_objectives_alignment(
        data(
            project=project(
                problem_statement="Comment optimiser la fermentation du cacao ?",
                general_objective="Étudier les华尔勒 de l'amidon.",
                specific_objectives=(),
            )
        )
    )
    assert outcome.findings
    assert outcome.findings[0].severity == Severity.WARNING


def test_problem_and_objectives_sharing_a_word_are_accepted() -> None:
    assert checks.check_problem_objectives_alignment(data()).findings == []


def test_coherence_is_inconclusive_without_objectives() -> None:
    outcome = checks.check_problem_objectives_alignment(
        data(project=project(general_objective=None, specific_objectives=()))
    )
    assert outcome.skipped_reason
    assert outcome.findings == []


def test_hypotheses_without_results_are_reported() -> None:
    outcome = checks.check_hypotheses_results_alignment(
        data(sections=[section(title="Introduction"), section(title="Conclusion")])
    )
    titles = " ".join(finding.title for finding in outcome.findings)
    assert "sans résultats" in titles


def test_hypotheses_with_results_and_conclusion_are_accepted() -> None:
    outcome = checks.check_hypotheses_results_alignment(
        data(sections=[section(title="Résultats"), section(title="Conclusion")])
    )
    assert outcome.findings == []


def test_a_citation_pointing_outside_the_bibliography_is_a_blocker() -> None:
    outcome = checks.check_citation_bibliography_alignment(
        data(references=[], citations=[citation("unknown-ref")])
    )
    assert outcome.findings
    assert outcome.findings[0].severity == Severity.BLOCKER
    assert outcome.findings[0].count == 1


def test_consistent_citations_and_bibliography_produce_no_finding() -> None:
    ref = reference()
    assert checks.check_citation_bibliography_alignment(
        data(references=[ref], citations=[citation(ref.reference_id)])
    ).findings == []


def test_a_very_low_bibliographic_coverage_is_reported_as_information() -> None:
    outcome = checks.check_uncited_ratio(
        data(references=[reference(f"ref{i}") for i in range(10)], citations=[])
    )
    assert outcome.findings
    assert outcome.findings[0].severity == Severity.INFO


def test_coverage_is_inconclusive_on_an_empty_library() -> None:
    outcome = checks.check_uncited_ratio(data(references=[]))
    assert outcome.skipped_reason


# --------------------------------------------------------------- statistics


def test_statistics_count_the_stored_data() -> None:
    ref = reference()
    payload = compute_stats(
        data(
            sections=[section(words=1000), section(title="Conclusion", words=3000, level=1)],
            references=[ref, reference("martin2023", year=2020)],
            citations=[
                citation(ref.reference_id),
                citation(ref.reference_id),
                citation("unknown-ref", orphaned=True, text="[Citation invalide]"),
            ],
            sources=[source()],
        )
    ).as_dict()
    assert payload["word_count"] == 4000
    assert payload["section_count"] == 2
    assert payload["citation_count"] == 3
    assert payload["reference_count"] == 2
    assert payload["distinct_cited_references"] == 1
    assert payload["uncited_reference_count"] == 1
    assert payload["orphan_citation_count"] == 1
    assert payload["source_count"] == 1
    assert payload["figure_count"] == 2
    assert payload["most_cited_references"][0]["count"] == 2


def test_reading_time_uses_two_hundred_words_per_minute() -> None:
    payload = compute_stats(data(sections=[section(words=2000)])).as_dict()
    assert payload["read_minutes"] == 10.0


def test_citation_density_is_none_on_an_empty_memoir_not_zero() -> None:
    payload = compute_stats(data(sections=[], citations=[])).as_dict()
    assert payload["citation_density"] is None


def test_per_section_density_is_none_when_the_section_is_empty() -> None:
    payload = compute_stats(data(sections=[section(words=0, citations=0)])).as_dict()
    assert payload["sections"][0]["citation_density"] is None


def test_reference_years_span_is_reported() -> None:
    payload = compute_stats(
        data(references=[reference("a", year=2010), reference("b", year=2024)])
    ).as_dict()
    assert payload["reference_year_span"] == [2010, 2024]


def test_an_empty_memoir_is_reported_as_such() -> None:
    observations = volume_observations(compute_stats(data(sections=[])))
    assert observations[0]["code"] == "volume.vide"


def test_a_long_section_is_observed_without_judgement() -> None:
    observations = volume_observations(compute_stats(data(sections=[section(words=20000)])))
    assert any(item["code"] == "volume.long" for item in observations)
    assert all("mauvais" not in item["detail"] for item in observations)


# ------------------------------------------------------------------- report


def test_the_report_runs_every_check() -> None:
    outcomes = run_checks(data())
    assert len(outcomes) == len(ALL_CHECKS)


def test_the_report_counts_and_sorts_the_findings() -> None:
    payload = data(
        references=[reference(authors=0, year=None)],
        citations=[citation(orphaned=True)],
        sections=[section(words=0, status="empty")],
    )
    outcomes = run_checks(payload)
    report = build_audit_report(payload, outcomes, compute_stats(payload))
    assert report["summary"]["blockers"] >= 1
    severities = [finding["severity"] for finding in report["findings"]]
    assert severities == sorted(severities, key=lambda name: Severity(name).rank)


def test_a_clean_memoir_is_ready_but_still_disclaims() -> None:
    ref = reference()
    payload = data(
        sections=[
            section(title="Matériel et méthodes"),
            section(title="Résultats"),
            section(title="Conclusion"),
        ],
        references=[ref],
        citations=[citation(ref.reference_id)],
        sources=[source()],
    )
    report = build_audit_report(payload, run_checks(payload), compute_stats(payload))
    assert report["readiness"]["level"] == "aucun_bloquant"
    # Readiness is never presented as a validation.
    assert "ne vaut pas validation" in report["readiness"]["detail"]
    assert "ne remplace pas" in report["disclaimer"]


def test_blockers_drive_the_readiness_level() -> None:
    payload = data(citations=[citation(orphaned=True)])
    report = build_audit_report(payload, run_checks(payload), compute_stats(payload))
    assert report["readiness"]["level"] in {"corrections_requises", "reprise_necessaire"}


def test_no_readiness_score_is_invented() -> None:
    payload = data()
    report = build_audit_report(payload, run_checks(payload), compute_stats(payload))
    # A percentage would imply a precision the checks do not have.
    assert "score" not in report["readiness"]
    assert "%" not in report["readiness"]["label"]


def test_inconclusive_checks_are_counted_and_surfaced() -> None:
    payload = data(expected_section_count=None, sections=[])
    report = build_audit_report(payload, run_checks(payload), compute_stats(payload))
    assert report["summary"]["checks_inconclusive"] >= 1
    checklist_labels = {item["category"] for item in report["defence_checklist"]}
    assert INSUFFICIENT_LABEL in checklist_labels


def test_the_defence_checklist_starts_with_the_blockers() -> None:
    payload = data(citations=[citation(orphaned=True)])
    report = build_audit_report(payload, run_checks(payload), compute_stats(payload))
    assert report["defence_checklist"][0]["priority"] == 1


def test_the_checklist_asks_rather_than_acts() -> None:
    payload = data()
    report = build_audit_report(payload, run_checks(payload), compute_stats(payload))
    for item in report["defence_checklist"]:
        assert isinstance(item["question"], str)
        assert item["question"]


def test_the_checklist_flags_an_orphan_citation_as_visible_to_a_jury() -> None:
    payload = data(citations=[citation(orphaned=True)])
    stats = compute_stats(payload)
    checklist = build_defence_checklist([], stats, [])
    assert any("orpheline" in item["question"] for item in checklist)


def test_no_finding_proposes_an_automatic_write() -> None:
    """The audit signals; it must never claim it can repair the memoir."""
    payload = data(
        references=[reference(authors=0, year=None)],
        citations=[citation(orphaned=True)],
        sections=[section(words=0, status="empty")],
    )
    report = build_audit_report(payload, run_checks(payload), compute_stats(payload))
    for finding in report["findings"]:
        remedy = (finding["remedy"] or "").casefold()
        for forbidden in ("automatiquement", "sera complété", "corrigé par l'application"):
            assert forbidden not in remedy


# ------------------------------------------------------------ determinism


def test_two_runs_on_the_same_data_produce_the_same_report() -> None:
    payload = data(
        references=[reference(authors=0, year=None)],
        citations=[citation(orphaned=True)],
    )
    first = build_audit_report(payload, run_checks(payload), compute_stats(payload))
    second = build_audit_report(payload, run_checks(payload), compute_stats(payload))
    first.pop("generated_at", None)
    second.pop("generated_at", None)
    assert first == second


def test_the_audit_never_calls_a_language_model() -> None:
    """The audit must be reproducible, so no provider may be involved."""
    for module in (checks, service):
        source = inspect.getsource(module).casefold()
        for forbidden in ("openai", "llmprovider", "chat.completions", "embedding", "httpx"):
            assert forbidden not in source, f"{module.__name__} references {forbidden}"


def test_the_audit_never_writes_to_the_memoir() -> None:
    """No statement about a section, a citation or a reference may appear in the audit."""
    source = inspect.getsource(service)
    for forbidden in (
        "update(section",
        "update(citation",
        "update(reference",
        "delete(section",
        "save_section_content",
        "upsert_citation",
    ):
        assert forbidden not in source.casefold()


# ---------------------------------------------------------------- routing


def _role_requirement(method: str, suffix: str) -> str:
    from fastapi.routing import APIRoute

    from app.audit.router import router

    for route in router.routes:
        if not isinstance(route, APIRoute):
            continue
        if method not in route.methods or not route.path.endswith(suffix):
            continue
        for dependency in route.dependant.dependencies:
            name = getattr(dependency.call, "__name__", "")
            if name.startswith("require_project_"):
                return name
        return "aucune"
    raise AssertionError(f"Route introuvable : {method} {suffix}")


@pytest.mark.parametrize(
    ("method", "suffix", "expected"),
    [
        ("GET", "/audit", "require_project_reader"),
        ("GET", "/audit/traces", "require_project_reader"),
        ("POST", "/audit/run", "require_project_editor"),
        ("DELETE", "/audit/traces/{trace_id}", "require_project_owner"),
    ],
)
def test_each_audit_route_requires_the_expected_role(
    method: str, suffix: str, expected: str
) -> None:
    assert _role_requirement(method, suffix) == expected


def test_running_an_audit_requires_csrf() -> None:
    from fastapi.routing import APIRoute

    from app.audit.router import router

    for route in router.routes:
        if not isinstance(route, APIRoute):
            continue
        if route.methods is None or "POST" not in route.methods:
            continue
        names = [
            getattr(dependency.call, "__name__", "")
            for dependency in route.dependant.dependencies
        ]
        assert "require_csrf" in names, f"{route.path} n'exige pas de jeton CSRF."


def test_every_audit_route_is_scoped_to_a_project() -> None:
    from app.audit.router import router

    for route in router.routes:
        assert "{project_id}" in route.path


def test_a_reader_may_read_the_audit_but_not_run_a_trace() -> None:
    """Seeing what is missing is not a privilege; storing a record is."""
    assert _role_requirement("GET", "/audit") == "require_project_reader"
    assert _role_requirement("POST", "/audit/run") == "require_project_editor"
