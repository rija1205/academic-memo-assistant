"""Shared normalisation helpers for academic metadata.

These functions are the single source of truth for the canonical forms used by the source
library (stage 5) and the bibliography (stage 9). A DOI, a title or a tag must be compared
the same way everywhere, otherwise duplicate detection silently disagrees with itself.

Nothing here invents a value: every function either returns a normalised form of its input or
``None``. A missing DOI stays ``None``; it is never replaced by a guess.
"""

from __future__ import annotations

import re
import unicodedata
from urllib.parse import unquote, urlsplit, urlunsplit

#: Prefixes that carry no information in a DOI and must be stripped for comparison.
_DOI_PREFIXES = (
    "https://doi.org/",
    "http://doi.org/",
    "https://dx.doi.org/",
    "http://dx.doi.org/",
    "https://www.doi.org/",
    "http://www.doi.org/",
    "doi:",
    "doi/",
    "info:doi/",
)

_DOI_ALLOWED = re.compile(r"^10\.\d{1,9}/\S+$", re.IGNORECASE)
_WHITESPACE = re.compile(r"\s+")
_PUNCTUATION = re.compile(r"[^\w\s]", re.UNICODE)


def normalize_doi(value: str | None) -> str | None:
    """Return the canonical DOI form, or ``None`` when there is no DOI.

    ``10.1234/example``, ``https://doi.org/10.1234/example``,
    ``https://dx.doi.org/10.1234/example`` and ``doi:10.1234/example`` all normalise to
    ``10.1234/example``.
    """
    if value is None:
        return None
    candidate = value.strip()
    if not candidate:
        return None
    lowered = candidate.casefold()
    for prefix in _DOI_PREFIXES:
        if lowered.startswith(prefix):
            candidate = candidate[len(prefix) :]
            lowered = candidate.casefold()
            break
    candidate = candidate.strip()
    if not candidate or not _DOI_ALLOWED.match(candidate):
        return None
    # DOIs are case-insensitive; the suffix is conventionally lower-cased.
    return candidate.lower()


def is_valid_doi(value: str | None) -> bool:
    """True when a DOI is syntactically usable."""
    return normalize_doi(value) is not None


def normalize_title(value: str | None) -> str:
    """Normalised title used for comparison: case-folded, unaccented, punctuation-free."""
    if not value:
        return ""
    decomposed = unicodedata.normalize("NFKD", value)
    without_accents = "".join(char for char in decomposed if not unicodedata.combining(char))
    without_punctuation = _PUNCTUATION.sub(" ", without_accents)
    return _WHITESPACE.sub(" ", without_punctuation).strip().casefold()


def normalize_tag(value: str) -> str:
    """Normalised tag used as a comparison key."""
    return _WHITESPACE.sub(" ", (value or "").strip()).casefold()


def normalize_url(value: str | None) -> str | None:
    """Normalise a URL without breaking it.

    Only the scheme and host are lower-cased and the default port is dropped. The path, the
    query string and the fragment are preserved verbatim, because a valid URL must not be
    altered beyond recognition.
    """
    if value is None:
        return None
    candidate = value.strip()
    if not candidate:
        return None
    if "//" not in candidate:
        # A bare value is only accepted when it looks like a host:port/path. Anything with
        # an opaque scheme such as "javascript:alert(1)" is rejected instead of being
        # rewritten into an https URL, which would turn an attack string into a fetchable one.
        if not re.match(r"^[A-Za-z0-9.-]+(:\d+)?(/|$)", candidate):
            return None
        candidate = f"https://{candidate}"
    try:
        parts = urlsplit(candidate)
    except ValueError:
        return None
    if not parts.scheme or not parts.netloc:
        return None
    scheme = parts.scheme.casefold()
    if scheme not in {"http", "https"}:
        return None
    netloc = parts.netloc.casefold()
    if netloc.endswith(":80") and scheme == "http":
        netloc = netloc[: -len(":80")]
    if netloc.endswith(":443") and scheme == "https":
        netloc = netloc[: -len(":443")]
    path = parts.path or "/"
    return urlunsplit((scheme, netloc, path, parts.query, parts.fragment))


def title_similarity(left: str | None, right: str | None) -> float:
    """Token-based similarity between two titles, in ``[0, 1]``.

    This is the Sørensen–Dice coefficient over word tokens, computed in pure Python so the
    project keeps no extra dependency. It is intentionally explainable: a duplicate report can
    state the score it used.
    """
    left_tokens = set(normalize_title(left).split())
    right_tokens = set(normalize_title(right).split())
    if not left_tokens or not right_tokens:
        return 0.0
    intersection = len(left_tokens & right_tokens)
    return (2.0 * intersection) / (len(left_tokens) + len(right_tokens))


def unescape_url_component(value: str) -> str:
    """Decode a percent-encoded URL component, used when reading CSL-like inputs."""
    return unquote(value)


__all__ = [
    "is_valid_doi",
    "normalize_doi",
    "normalize_tag",
    "normalize_title",
    "normalize_url",
    "title_similarity",
    "unescape_url_component",
]
