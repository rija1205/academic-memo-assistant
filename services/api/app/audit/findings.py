"""The finding model of the academic audit.

An audit **signals**; it never repairs. A finding therefore always carries three things:

* what is wrong, stated factually;
* where it is, so the author can go and look;
* what to do about it, as an action the author performs.

A finding never contains a rewritten sentence, a guessed author or a suggested year. If the
data is missing, the audit says so instead of filling the gap, which is why
:data:`MISSING_LABEL` is a first-class value rather than a formatting accident.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

#: The label used whenever a piece of academic metadata is absent. Never a guess.
MISSING_LABEL = "Non renseigné"

#: Used when a check cannot conclude because the underlying data is insufficient.
INSUFFICIENT_LABEL = "Source insuffisante"

#: Used when the author must look at something themselves.
TO_VERIFY_LABEL = "À vérifier"


class Severity(StrEnum):
    """How much a finding blocks a deposit.

    ``BLOCKER`` means the memoir cannot be defended as it stands. ``WARNING`` means a jury
    would likely raise it. ``INFO`` is a neutral observation, useful for statistics.
    """

    BLOCKER = "blocker"
    WARNING = "warning"
    INFO = "info"

    @property
    def rank(self) -> int:
        return {"blocker": 0, "warning": 1, "info": 2}[self.value]


#: Ordered so a report can be rendered front to back.
SEVERITY_LABELS: dict[str, str] = {
    Severity.BLOCKER.value: "Bloquant",
    Severity.WARNING.value: "À vérifier",
    Severity.INFO.value: "Information",
}


@dataclass(frozen=True, slots=True)
class Finding:
    """One problem or observation, with its location and its remedy."""

    code: str
    severity: Severity
    title: str
    detail: str
    #: Where to look: a section id, a reference key, a node id, or ``None`` for the project.
    location_kind: str | None = None
    location_ref: str | None = None
    location_label: str | None = None
    #: What the author should do, phrased as an action and never as an automatic change.
    remedy: str | None = None
    #: Number of occurrences, for findings that group several items.
    count: int = 1
    #: Extra structured detail, used by the interface to link to the object.
    meta: dict[str, object] = field(default_factory=dict)

    def as_dict(self) -> dict[str, object]:
        return {
            "code": self.code,
            "severity": self.severity.value,
            "severity_label": SEVERITY_LABELS[self.severity.value],
            "title": self.title,
            "detail": self.detail,
            "location_kind": self.location_kind,
            "location_ref": self.location_ref,
            "location_label": self.location_label,
            "remedy": self.remedy,
            "count": self.count,
            "meta": self.meta,
        }

    def sort_key(self) -> tuple[int, str, str]:
        return (self.severity.rank, self.code, self.location_ref or "")


@dataclass(slots=True)
class CheckOutcome:
    """The result of one check: its findings, or the reason it could not conclude."""

    code: str
    findings: list[Finding] = field(default_factory=list)
    #: Set when the check was skipped for lack of data. The report shows it as
    #: ``INSUFFICIENT_LABEL`` rather than as a pass, so a silent gap is never read as success.
    skipped_reason: str | None = None

    @property
    def has_findings(self) -> bool:
        return bool(self.findings)


__all__ = [
    "INSUFFICIENT_LABEL",
    "MISSING_LABEL",
    "SEVERITY_LABELS",
    "TO_VERIFY_LABEL",
    "CheckOutcome",
    "Finding",
    "Severity",
]
