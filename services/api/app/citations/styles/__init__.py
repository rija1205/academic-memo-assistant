"""The citation style registry.

One registry, one lookup. Adding a style means adding one class and one entry here; no
endpoint, no React component and no migration has to change.

Aliases exist because ``projects.bibliography_style`` already holds the value ``"apa"``
(default set in migration ``0003``) while the style is named ``APA7`` everywhere else. The
alias map resolves the stored value without rewriting the user's choice.
"""

from __future__ import annotations

from app.citations.styles.apa import Apa7Style
from app.citations.styles.base import CitationStyle
from app.citations.styles.harvard import HarvardStyle
from app.citations.styles.iso690 import Iso690Style
from app.citations.styles.vancouver import VancouverStyle

#: Style used when a project has no explicit choice. It matches the column default.
DEFAULT_STYLE = "apa7"

#: canonical name -> class
STYLE_REGISTRY: dict[str, type[CitationStyle]] = {
    Apa7Style.name: Apa7Style,
    HarvardStyle.name: HarvardStyle,
    VancouverStyle.name: VancouverStyle,
    Iso690Style.name: Iso690Style,
}

#: Everything a stored or user-supplied value may look like, mapped to a canonical name.
STYLE_ALIASES: dict[str, str] = {
    "apa": "apa7",
    "apa7": "apa7",
    "apa-7": "apa7",
    "apa 7": "apa7",
    "apaseventh": "apa7",
    "harvard": "harvard",
    "harvardauthor": "harvard",
    "author-date": "harvard",
    "authordate": "harvard",
    "vancouver": "vancouver",
    "icmje": "vancouver",
    "numeric": "vancouver",
    "iso690": "iso690",
    "iso-690": "iso690",
    "iso 690": "iso690",
    "iso690numeric": "iso690",
}


class UnknownCitationStyle(ValueError):
    """Raised when a style name is not registered."""

    def __init__(self, value: str) -> None:
        super().__init__(
            f"Style bibliographique inconnu : {value!r}. "
            f"Styles disponibles : {', '.join(sorted(STYLE_REGISTRY))}."
        )
        self.value = value


def normalise_style_name(value: str | None) -> str:
    """Resolve any accepted spelling to a canonical style name.

    An unknown or empty value falls back to the default rather than raising, so a project with
    a legacy value still renders. The user's stored choice is never silently rewritten: this
    only decides how to interpret it.
    """
    if not value:
        return DEFAULT_STYLE
    key = value.strip().casefold()
    if key in STYLE_REGISTRY:
        return key
    return STYLE_ALIASES.get(key, DEFAULT_STYLE)


def resolve_style_name(value: str | None) -> str:
    """Same as :func:`normalise_style_name` but raises on an unknown style.

    Used where a typo must be reported rather than silently replaced.
    """
    if not value:
        return DEFAULT_STYLE
    key = value.strip().casefold()
    if key in STYLE_REGISTRY:
        return key
    alias = STYLE_ALIASES.get(key)
    if alias is None:
        raise UnknownCitationStyle(value)
    return alias


def get_style(value: str | None) -> CitationStyle:
    """Return the style instance for a stored or user-supplied name."""
    return STYLE_REGISTRY[normalise_style_name(value)]()


def available_styles() -> list[dict[str, object]]:
    """The catalogue shown in the interface, in presentation order."""
    order = ["apa7", "harvard", "vancouver", "iso690"]
    return [
        {
            "name": name,
            "label": STYLE_REGISTRY[name].label,
            "uses_numbers": STYLE_REGISTRY[name].uses_numbers,
            "date_missing": STYLE_REGISTRY[name].date_missing,
        }
        for name in order
        if name in STYLE_REGISTRY
    ]


__all__ = [
    "DEFAULT_STYLE",
    "STYLE_ALIASES",
    "STYLE_REGISTRY",
    "UnknownCitationStyle",
    "available_styles",
    "get_style",
    "normalise_style_name",
    "resolve_style_name",
]
