"""Observability: structured logging and in-process metrics.

Two things an operator needs and that the application did not provide:

* **structured logs.** One JSON object per line, with a request identifier so a user report
  can be traced across the API, the worker and the database. Secrets never reach a log line:
  the formatter redacts the keys that would carry them, whatever the caller passes.
* **metrics.** Counters and latency percentiles kept in process and exposed on an endpoint the
  platform can scrape. They are deliberately dependency-free: a monitoring library would be a
  new supply chain for numbers the project can compute itself.

The metrics are per-process and reset on restart. That is stated in the payload rather than
hidden, because a dashboard that silently shows a partial view is worse than one that says so.
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

#: Keys whose value must never appear in a log line.
REDACTED_KEYS = frozenset(
    {
        "password",
        "new_password",
        "current_password",
        "token",
        "access_token",
        "refresh_token",
        "reset_token",
        "csrf_token",
        "authorization",
        "cookie",
        "set-cookie",
        "api_key",
        "secret",
        "client_secret",
        "openai_api_key",
        "s3_secret_key",
    }
)

#: Substrings that mark a value as secret even when the key is innocuous.
REDACTED_SUBSTRINGS = ("password", "token", "secret", "api_key", "apikey", "authorization")

REDACTED = "[redacted]"


def redact(payload: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of ``payload`` with every secret-looking value replaced."""
    safe: dict[str, Any] = {}
    for key, value in payload.items():
        lowered = str(key).casefold()
        if lowered in REDACTED_KEYS or any(marker in lowered for marker in REDACTED_SUBSTRINGS):
            safe[key] = REDACTED
            continue
        if isinstance(value, dict):
            safe[key] = redact(value)
        elif isinstance(value, str) and len(value) > 2000:
            safe[key] = value[:2000] + "…"
        else:
            safe[key] = value
    return safe


def log(level: str, message: str, **fields: Any) -> None:
    """Emit one structured line on the standard output.

    A JSON line is greppable, parsable by any collector, and never interleaves a message with
    a value the way a formatted string does.
    """
    import json
    import sys

    record = {
        "ts": datetime.now(UTC).isoformat(timespec="milliseconds"),
        "level": level,
        "message": message,
        **redact(fields),
    }
    try:
        line = json.dumps(record, ensure_ascii=False, default=repr)
    except Exception:  # noqa: BLE001 - a log line must never raise, whatever it is handed
        # Even a value whose repr explodes must not break the caller, so the whole record is
        # reduced to its scalar fields.
        line = json.dumps(
            {
                key: value
                for key, value in record.items()
                if isinstance(value, (str, int, float, bool, type(None)))
            },
            ensure_ascii=False,
        )
    try:
        sys.stdout.write(line + "\n")
    except Exception:  # noqa: BLE001 - stdout must never break a request
        pass


def info(message: str, **fields: Any) -> None:
    log("INFO", message, **fields)


def warning(message: str, **fields: Any) -> None:
    log("WARNING", message, **fields)


def error(message: str, **fields: Any) -> None:
    log("ERROR", message, **fields)


# ------------------------------------------------------------------- metrics


@dataclass(slots=True)
class Histogram:
    """A bounded reservoir of recent durations, enough for percentiles without unbounded RAM."""

    window: int = 512
    values: deque[float] = field(default_factory=deque)

    def observe(self, value: float) -> None:
        self.values.append(value)
        while len(self.values) > self.window:
            self.values.popleft()

    def percentile(self, fraction: float) -> float | None:
        if not self.values:
            return None
        ordered = sorted(self.values)
        index = min(int(len(ordered) * fraction), len(ordered) - 1)
        return round(ordered[index], 2)

    def as_dict(self) -> dict[str, Any]:
        if not self.values:
            return {"count": 0}
        return {
            "count": len(self.values),
            "p50": self.percentile(0.50),
            "p95": self.percentile(0.95),
            "p99": self.percentile(0.99),
            "max": round(max(self.values), 2),
        }


class MetricsRegistry:
    """Counters and latency histograms for one process."""

    def __init__(self) -> None:
        self.started_at = datetime.now(UTC)
        self.requests: dict[str, int] = defaultdict(int)
        self.errors: dict[str, int] = defaultdict(int)
        self.rate_limited: int = 0
        self.security_events: dict[str, int] = defaultdict(int)
        self.exports: dict[str, int] = defaultdict(int)
        self.rag_queries: int = 0
        self.llm_calls: int = 0
        self.llm_tokens: int = 0
        self.latency: Histogram = Histogram()
        self.by_route: dict[str, Histogram] = {}

    def observe_request(
        self, *, route: str, status_code: int, duration_ms: float
    ) -> None:
        """Record one HTTP exchange."""
        self.requests[route] += 1
        self.latency.observe(duration_ms)
        self.by_route.setdefault(route, Histogram()).observe(duration_ms)
        if status_code >= 500:
            self.errors[route] += 1
        elif status_code == 429:
            self.rate_limited += 1

    def observe_security_event(self, kind: str) -> None:
        self.security_events[kind] += 1

    def observe_export(self, export_format: str) -> None:
        self.exports[export_format] += 1

    def observe_llm(self, tokens: int) -> None:
        self.llm_calls += 1
        self.llm_tokens += tokens

    def snapshot(self, version: str) -> dict[str, Any]:
        """The metrics payload, stating plainly that it is per process."""
        uptime = (datetime.now(UTC) - self.started_at).total_seconds()
        return {
            "version": version,
            "scope": "process",
            "warning": (
                "Métriques par processus : un déploiement multi-instance doit les agréger."
            ),
            "started_at": self.started_at.isoformat(),
            "uptime_seconds": round(uptime, 1),
            "requests": {
                "total": sum(self.requests.values()),
                "by_route": dict(sorted(self.requests.items())),
                "errors_5xx": sum(self.errors.values()),
                "rate_limited": self.rate_limited,
            },
            "latency_ms": self.latency.as_dict(),
            "by_route": {
                route: histogram.as_dict()
                for route, histogram in sorted(self.by_route.items())
            },
            "security_events": dict(sorted(self.security_events.items())),
            "exports": dict(sorted(self.exports.items())),
            "llm": {"calls": self.llm_calls, "tokens": self.llm_tokens},
            "rag_queries": self.rag_queries,
        }

    def reset(self) -> None:
        self.requests.clear()
        self.errors.clear()
        self.security_events.clear()
        self.exports.clear()
        self.by_route.clear()
        self.latency = Histogram()
        self.rate_limited = 0
        self.rag_queries = 0
        self.llm_calls = 0
        self.llm_tokens = 0


#: The registry of this process, created at import so the middleware can reach it.
REGISTRY = MetricsRegistry()


def route_of(request: Any) -> str:
    """A stable route label.

    The concrete identifier is replaced by its parameter name, so a metric never becomes a
    catalogue of project identifiers.
    """
    route = getattr(getattr(request, "scope", {}), "get", lambda _key: None)("route")
    path = getattr(route, "path", None)
    if path:
        return str(path)
    template = request.url.path
    parts = []
    for segment in template.split("/"):
        parts.append(segment if not _looks_like_identifier(segment) else "{id}")
    return "/".join(parts)


def _looks_like_identifier(segment: str) -> bool:
    return len(segment) >= 32 and segment.count("-") >= 4


__all__ = [
    "REDACTED",
    "REDACTED_KEYS",
    "REGISTRY",
    "Histogram",
    "MetricsRegistry",
    "error",
    "info",
    "log",
    "redact",
    "route_of",
    "warning",
]
