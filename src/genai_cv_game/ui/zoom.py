"""Zoomable images (Streamlit Custom Component v2, inline).

Hover zooms in place; a click opens a full-screen viewer (see `zoom_image.js`).
The images are not sent through Streamlit: the browser loads them from
Streamlit's static file server (`server.enableStaticServing`, folder `static/`)
and caches them. Each image may have a larger `<name>_zoom.<ext>` sibling that
is fetched lazily on first hover and swapped in.

`zoom_image` returns False when zooming isn't possible (static serving off or
not actually working on this server, file outside `static/`, missing file);
callers then fall back to a plain `st.image`.
"""

from __future__ import annotations

import functools
import os
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

import requests
import streamlit as st
from PIL import Image

_DIR = Path(__file__).parent
_STATIC_PREFIX = "static/"
_ASPECT_TOLERANCE = 0.03  # same aspect ratio within 3 % -> zoom/pan can be linked
_PROBE_SECONDS = 30  # how long a "does static serving work?" answer is reused
_probe = {"at": -1e9, "ok": False}

_COMPONENT = st.components.v2.component(
    "genai_cv_game_zoom_image",
    html=(_DIR / "zoom_image.html").read_text(),
    css=(_DIR / "zoom_image.css").read_text(),
    js=(_DIR / "zoom_image.js").read_text(),
)


@dataclass(frozen=True)
class ZoomGroup:
    """Images that open together in the viewer (e.g. a real/AI pair).

    `pos` orders them left to right; `sync` links their zoom and pan (only
    sensible when they show the same framing, i.e. have the same aspect ratio).
    """

    id: str
    pos: int = 0
    sync: bool = False


def zoom_available() -> bool:
    """Whether the zoom viewer may be used: static serving is enabled in the
    configuration and `ENABLE_ZOOM` is not set to a false value.

    `ENABLE_ZOOM=false` is the escape hatch for hosts where the server can reach
    its own `/app/static/` but browsers cannot (proxies): plain `st.image` is used.
    """
    if os.environ.get("ENABLE_ZOOM", "true").strip().lower() in {"0", "false", "no"}:
        return False
    return bool(st.get_option("server.enableStaticServing"))


def static_serving_works(url: str) -> bool:
    """Whether this server really serves `url` (a /app/static/... path) as an image.

    The config can say "enabled" while a server that was started earlier does
    not serve the folder (it only mounts it at startup). Then the request falls
    through to Streamlit's catch-all page and comes back as HTML, so check the
    content type. The answer is reused for `_PROBE_SECONDS`.
    """
    now = time.monotonic()
    if now - _probe["at"] < _PROBE_SECONDS:
        return bool(_probe["ok"])
    ok = False
    try:
        port = int(st.get_option("server.port"))
        with requests.get(f"http://127.0.0.1:{port}{url}", timeout=2, stream=True) as r:
            ok = r.ok and r.headers.get("content-type", "").startswith("image/")
    except requests.RequestException, TypeError, ValueError:
        ok = False
    _probe.update(at=now, ok=ok)
    return ok


def static_url(path: str | Path) -> str | None:
    """URL of a file below `static/` as served by Streamlit, else None."""
    rel = Path(path).as_posix()
    if not rel.startswith(_STATIC_PREFIX):
        return None
    base = str(st.get_option("server.baseUrlPath") or "").strip("/")
    prefix = f"/{base}" if base else ""
    return f"{prefix}/app/{quote(rel)}"


def zoom_variant(path: str | Path) -> str | None:
    """Path of the larger `<stem>_zoom<suffix>` sibling, if it exists."""
    p = Path(path)
    z = p.with_name(f"{p.stem}_zoom{p.suffix}")
    return z.as_posix() if z.exists() else None


@functools.lru_cache(maxsize=256)
def _size_cached(path: str, mtime_ns: int) -> tuple[int, int]:
    with Image.open(path) as im:  # reads the header only
        return im.size


def image_size(path: str | Path) -> tuple[int, int] | None:
    try:
        return _size_cached(str(path), Path(path).stat().st_mtime_ns)
    except OSError:
        return None


def same_aspect(a: str | Path, b: str | Path) -> bool:
    """Whether two images have (nearly) the same aspect ratio."""
    sa, sb = image_size(a), image_size(b)
    if sa is None or sb is None:
        return False
    ra, rb = sa[0] / sa[1], sb[0] / sb[1]
    return abs(ra - rb) / ra <= _ASPECT_TOLERANCE


def zoom_image(
    path: str | Path,
    *,
    key: str,
    group: ZoomGroup,
    alt: str,
    label: str = "",
    zoom: float = 3.0,
) -> bool:
    """Render a zoomable image. Returns False if the caller must fall back."""
    url = static_url(path)
    size = image_size(path)
    if url is None or size is None or not zoom_available():
        return False
    if not static_serving_works(url):
        return False
    big = zoom_variant(path)
    _COMPONENT(
        key=key,
        data={
            "id": key,
            "src": url,
            "zoomSrc": static_url(big) if big else None,
            "w": size[0],
            "h": size[1],
            "alt": alt,
            "label": label,
            "group": group.id,
            "pos": group.pos,
            "sync": group.sync,
            "zoom": zoom,
        },
        width="stretch",
        height="content",
    )
    return True
