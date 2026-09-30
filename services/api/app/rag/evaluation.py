"""Retrieval quality metrics computed on a real labelled dataset.

No score is invented here. Every metric is computed from passages that are actually
present in the test dataset and from relevance judgements that are written down in the
dataset itself:

* ``precision_at_k`` - fraction of the top-k retrieved passages that are relevant;
* ``recall_at_k``    - fraction of the expected relevant passages that appear in the top-k;
* ``mrr``            - mean reciprocal rank of the first relevant passage;
* ``ndcg_at_k``      - normalised discounted cumulative gain;
* ``latency_ms``     - measured wall-clock time of the retrieval call.

A judgement is the set of chunk keys that a human would consider correct for a question.
"""

from __future__ import annotations

import math
import time
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class RelevanceJudgement:
    """One labelled question and the chunk keys considered correct."""

    question: str
    relevant_keys: frozenset[str]
    note: str = ""


@dataclass(frozen=True, slots=True)
class RankedPassage:
    """A retrieved passage reduced to its dataset key."""

    key: str
    rank: int


@dataclass(frozen=True, slots=True)
class CaseResult:
    question: str
    precision_at_k: float
    recall_at_k: float
    reciprocal_rank: float
    ndcg_at_k: float
    latency_ms: float
    retrieved_keys: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "question": self.question,
            "precision_at_k": round(self.precision_at_k, 4),
            "recall_at_k": round(self.recall_at_k, 4),
            "reciprocal_rank": round(self.reciprocal_rank, 4),
            "ndcg_at_k": round(self.ndcg_at_k, 4),
            "latency_ms": round(self.latency_ms, 2),
            "retrieved_keys": self.retrieved_keys,
        }


@dataclass(frozen=True, slots=True)
class QualityReport:
    """Aggregated quality of a retrieval run over the labelled dataset."""

    cases: list[CaseResult]
    k: int

    @property
    def mean_precision_at_k(self) -> float:
        return _mean([case.precision_at_k for case in self.cases])

    @property
    def mean_recall_at_k(self) -> float:
        return _mean([case.recall_at_k for case in self.cases])

    @property
    def mean_reciprocal_rank(self) -> float:
        return _mean([case.reciprocal_rank for case in self.cases])

    @property
    def mean_ndcg_at_k(self) -> float:
        return _mean([case.ndcg_at_k for case in self.cases])

    @property
    def mean_latency_ms(self) -> float:
        return _mean([case.latency_ms for case in self.cases])

    @property
    def max_latency_ms(self) -> float:
        return max((case.latency_ms for case in self.cases), default=0.0)

    def as_dict(self) -> dict[str, Any]:
        return {
            "k": self.k,
            "case_count": len(self.cases),
            "mean_precision_at_k": round(self.mean_precision_at_k, 4),
            "mean_recall_at_k": round(self.mean_recall_at_k, 4),
            "mean_reciprocal_rank": round(self.mean_reciprocal_rank, 4),
            "mean_ndcg_at_k": round(self.mean_ndcg_at_k, 4),
            "mean_latency_ms": round(self.mean_latency_ms, 2),
            "max_latency_ms": round(self.max_latency_ms, 2),
            "cases": [case.as_dict() for case in self.cases],
        }


def precision_at_k(ranked: Sequence[RankedPassage], relevant: frozenset[str], k: int) -> float:
    if k <= 0:
        raise ValueError("k must be positive")
    top = list(ranked)[:k]
    if not top:
        return 0.0
    hits = sum(1 for passage in top if passage.key in relevant)
    return hits / len(top)


def recall_at_k(ranked: Sequence[RankedPassage], relevant: frozenset[str], k: int) -> float:
    if not relevant:
        raise ValueError("a judgement must declare at least one relevant passage")
    top = list(ranked)[:k]
    hits = {passage.key for passage in top if passage.key in relevant}
    return len(hits) / len(relevant)


def reciprocal_rank(ranked: Sequence[RankedPassage], relevant: frozenset[str]) -> float:
    for position, passage in enumerate(ranked, start=1):
        if passage.key in relevant:
            return 1.0 / position
    return 0.0


def ndcg_at_k(ranked: Sequence[RankedPassage], relevant: frozenset[str], k: int) -> float:
    if not relevant:
        raise ValueError("a judgement must declare at least one relevant passage")
    top = list(ranked)[:k]
    dcg = sum(
        1.0 / math.log2(position + 1)
        for position, passage in enumerate(top, start=1)
        if passage.key in relevant
    )
    ideal_hits = min(len(relevant), k)
    idcg = sum(1.0 / math.log2(position + 1) for position in range(1, ideal_hits + 1))
    return dcg / idcg if idcg else 0.0


def evaluate_case(
    judgement: RelevanceJudgement,
    ranked: Sequence[RankedPassage],
    *,
    k: int,
    latency_ms: float,
) -> CaseResult:
    return CaseResult(
        question=judgement.question,
        precision_at_k=precision_at_k(ranked, judgement.relevant_keys, k),
        recall_at_k=recall_at_k(ranked, judgement.relevant_keys, k),
        reciprocal_rank=reciprocal_rank(ranked, judgement.relevant_keys),
        ndcg_at_k=ndcg_at_k(ranked, judgement.relevant_keys, k),
        latency_ms=latency_ms,
        retrieved_keys=[passage.key for passage in ranked],
    )


def evaluate(
    judgements: Iterable[RelevanceJudgement],
    retrievals: dict[str, Sequence[RankedPassage]],
    *,
    k: int = 5,
    latencies_ms: dict[str, float] | None = None,
) -> QualityReport:
    """Evaluate a retrieval run.

    Judgements without a retrieval are reported as zero instead of being skipped, so a
    missing result can never be mistaken for a good one. ``latencies_ms`` carries the measured
    wall-clock duration of each retrieval call.
    """
    measured = latencies_ms or {}
    cases: list[CaseResult] = []
    for judgement in judgements:
        ranked = list(retrievals.get(judgement.question, []))
        cases.append(
            evaluate_case(
                judgement,
                ranked,
                k=k,
                latency_ms=float(measured.get(judgement.question, 0.0)),
            )
        )
    return QualityReport(cases=cases, k=k)


class Timer:
    """Measure the wall-clock duration of a retrieval call in milliseconds."""

    def __init__(self) -> None:
        self.start = time.perf_counter()

    @property
    def elapsed_ms(self) -> float:
        return (time.perf_counter() - self.start) * 1000.0


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0
