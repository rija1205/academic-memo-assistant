"""Resolving the images of a document for an export.

The editor stores images as URLs, so an export has to decide what to do with each one. The
decision is security-relevant, because fetching a URL supplied by an author is a server-side
request forgery vector.

Rules, in order:

1. a ``data:`` URL is decoded in memory and embedded;
2. a ``blob:`` or ``file:`` URL is refused — a browser-only scheme, meaningless on the server;
3. an ``http(s)`` URL is embedded only when ``embed_remote_images`` is enabled, and then only
   after the host has been resolved and checked against the private, loopback, link-local and
   reserved ranges;
4. anything else is refused, and the figure keeps a reason so the PDF shows a placeholder
   instead of silently losing the image.

Every fetch is bounded in time and in size.
"""

from __future__ import annotations

import base64
import binascii
import ipaddress
import re
import socket
from urllib.parse import unquote_to_bytes, urlparse

#: Base64 payloads above this size are refused: a data URL is a memory allocation.
MAX_DATA_URL_BYTES = 12 * 1024 * 1024
#: Bytes read from a remote image before the download is aborted.
MAX_REMOTE_BYTES = 8 * 1024 * 1024
REMOTE_TIMEOUT_SECONDS = 10.0

_DATA_URL = re.compile(
    r"^data:(?P<mime>[\w.+-]+/[\w.+-]+)?(?P<base64>;base64)?,(?P<payload>.*)$",
    re.DOTALL,
)

SUPPORTED_IMAGE_TYPES = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/gif": "gif",
    "image/webp": "webp",
    "image/bmp": "bmp",
    "image/tiff": "tiff",
}


class ImageUnavailable(Exception):
    """Raised when an image cannot be embedded; the message becomes the placeholder reason."""


def _is_public_address(host: str) -> bool:
    """True when every resolved address of ``host`` is a routable public address.

    A hostname that resolves to a private, loopback, link-local, multicast or reserved address
    is refused. This is the check that stops an export from reaching the database host, the
    Redis container or a cloud metadata endpoint.
    """
    try:
        literal = ipaddress.ip_address(host)
        addresses = [literal]
    except ValueError:
        try:
            infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
        except OSError as exc:
            raise ImageUnavailable(f"Hôte introuvable : {host}.") from exc
        addresses = []
        for info in infos:
            try:
                addresses.append(ipaddress.ip_address(info[4][0]))
            except ValueError:
                continue
    if not addresses:
        raise ImageUnavailable(f"Hôte introuvable : {host}.")
    for address in addresses:
        if (
            address.is_private
            or address.is_loopback
            or address.is_link_local
            or address.is_multicast
            or address.is_reserved
            or address.is_unspecified
        ):
            raise ImageUnavailable(
                "Image distante non intégrée : l'adresse cible n'est pas publique."
            )
    return True


def resolve_data_url(url: str) -> tuple[bytes, str]:
    """Decode a ``data:`` URL into bytes and a content type."""
    match = _DATA_URL.match(url.strip())
    if match is None:
        raise ImageUnavailable("URL de données illisible.")
    mime = (match.group("mime") or "image/png").lower()
    if mime not in SUPPORTED_IMAGE_TYPES:
        raise ImageUnavailable(f"Type d'image non pris en charge : {mime}.")
    payload = match.group("payload") or ""
    try:
        if match.group("base64"):
            data = base64.b64decode(payload, validate=False)
        else:
            data = unquote_to_bytes(payload)
    except (binascii.Error, ValueError) as exc:
        raise ImageUnavailable("Contenu de l'image illisible.") from exc
    if not data:
        raise ImageUnavailable("Image vide.")
    if len(data) > MAX_DATA_URL_BYTES:
        raise ImageUnavailable("Image trop volumineuse pour l'export.")
    return data, mime


def resolve_remote_image(url: str) -> tuple[bytes, str]:
    """Download a remote image after checking that its host is public.

    Imported lazily so the module can be imported — and unit tested — without the HTTP client.
    """
    import httpx

    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ImageUnavailable("Schéma d'image non pris en charge.")
    host = parsed.hostname
    if not host:
        raise ImageUnavailable("URL d'image sans hôte.")
    _is_public_address(host)

    headers = {"User-Agent": REMOTE_USER_AGENT}
    try:
        with httpx.Client(
            follow_redirects=False, timeout=REMOTE_TIMEOUT_SECONDS, headers=headers
        ) as client:
            with client.stream("GET", url) as response:
                if response.status_code != 200:
                    raise ImageUnavailable(
                        f"Image distante indisponible (HTTP {response.status_code})."
                    )
                content_type = (
                    response.headers.get("content-type", "").split(";")[0].strip().lower()
                )
                if content_type not in SUPPORTED_IMAGE_TYPES:
                    raise ImageUnavailable(
                        f"Type d'image non pris en charge : {content_type or 'inconnu'}."
                    )
                declared = response.headers.get("content-length")
                if declared and declared.isdigit() and int(declared) > MAX_REMOTE_BYTES:
                    raise ImageUnavailable("Image distante trop volumineuse.")
                chunks: list[bytes] = []
                total = 0
                for chunk in response.iter_bytes(64 * 1024):
                    total += len(chunk)
                    if total > MAX_REMOTE_BYTES:
                        raise ImageUnavailable("Image distante trop volumineuse.")
                    chunks.append(chunk)
                return b"".join(chunks), content_type
    except httpx.HTTPError as exc:
        raise ImageUnavailable(f"Image distante inaccessible : {type(exc).__name__}.") from exc


REMOTE_USER_AGENT = "academic-memo-assistant/1.0 (academic export)"


def resolve_image(
    url: str | None, *, allow_remote: bool
) -> tuple[bytes | None, str | None, str | None]:
    """Return ``(data, content_type, unavailable_reason)``.

    Exactly one of ``data`` and ``unavailable_reason`` is set. A missing image is reported,
    never invented and never dropped without explanation.
    """
    if not url or not url.strip():
        return None, None, "Aucune image fournie."
    candidate = url.strip()
    scheme = candidate.split(":", 1)[0].lower() if ":" in candidate else ""
    try:
        if scheme == "data":
            data, content_type = resolve_data_url(candidate)
            return data, content_type, None
        if scheme in {"blob", "file", "javascript"}:
            # A browser-only scheme must never be dereferenced by the server.
            return None, None, "Schéma d'image non autorisé par l'export."
        if scheme in {"http", "https"}:
            if not allow_remote:
                return (
                    None,
                    None,
                    "Image distante non intégrée : activez « intégrer les images distantes » "
                    "pour l'exporter.",
                )
            data, content_type = resolve_remote_image(candidate)
            return data, content_type, None
        return None, None, "Schéma d'image non pris en charge."
    except ImageUnavailable as exc:
        return None, None, str(exc)


def image_size(data: bytes) -> tuple[int, int] | None:
    """Intrinsic size of an image, read with Pillow.

    Used to scale a figure to the text width without distorting it.
    """
    try:
        from io import BytesIO

        from PIL import Image

        with Image.open(BytesIO(data)) as image:
            return int(image.width), int(image.height)
    except Exception:
        # A corrupt or unsupported image must not break the export; the renderer falls back to
        # a fixed width and lets the height be estimated.
        return None


__all__ = [
    "MAX_DATA_URL_BYTES",
    "MAX_REMOTE_BYTES",
    "REMOTE_TIMEOUT_SECONDS",
    "SUPPORTED_IMAGE_TYPES",
    "ImageUnavailable",
    "image_size",
    "resolve_data_url",
    "resolve_image",
    "resolve_remote_image",
]
