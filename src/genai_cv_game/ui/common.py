"""Small UI helpers shared by several pages."""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from genai_cv_game.config import AppSettings
from genai_cv_game.model_catalog import display_name
from genai_cv_game.storage import resize_to_max_width
from genai_cv_game.utils import md_escape, truncate

# Default sidebar icon per task mode (a task can override it in tasks.json).
MODE_ICONS: dict[str, str] = {
    "text2img": ":material/brush:",
    "match": ":material/compare:",
    "edit": ":material/auto_fix_high:",
    "compose": ":material/layers:",
    "explore": ":material/upload:",
    "vote": ":material/how_to_vote:",
    "comparison": ":material/view_column:",
}

_PROMPT_PREVIEW_CHARS = 120
_ADMIN_KEY = "admin_authenticated"

PRIVACY_NOTE = (
    "Prompts and uploaded images are sent to an external AI provider "
    "(Replicate and the model's vendor) and stored on the class server for the "
    "day. Don't upload photos of other people without their consent, or "
    "anything private."
)


@st.cache_resource(max_entries=64, show_spinner=False)
def _asset_bytes(path: str, mtime_ns: int) -> bytes:
    return Path(path).read_bytes()


def asset_image(path: str | Path) -> bytes | None:
    """Bytes of a static asset image (vote/target/input), cached in memory.

    These files never change during class, and reading + hashing a dozen of them
    on every rerun was a noticeable share of each click. Generated images are
    not cached here (too many, too large for the server's memory). Returns None
    if the file is missing.
    """
    try:
        return _asset_bytes(str(path), Path(path).stat().st_mtime_ns)
    except FileNotFoundError:
        return None


# Pixels supplied per displayed pixel for thumbnails: sharp on retina screens and
# phones (3x), still small (a 170 px thumbnail is ~50 KB).
_HIDPI = 3


@st.cache_resource(max_entries=64, show_spinner=False)
def _thumb_bytes(path: str, mtime_ns: int, max_px: int) -> bytes:
    return resize_to_max_width(Path(path).read_bytes(), max_px)


def thumbnail(
    source: str | Path | bytes,
    width: int,
    *,
    caption: str | None = None,
    alt: str = "",
) -> None:
    """Show an image `width` CSS pixels wide, sharp on high-resolution screens.

    Do not use `st.image(width=<int>)` for this: Streamlit then shrinks the image
    server-side to exactly that many pixels (bilinear), so a 170 px thumbnail is
    stretched on retina screens and looks blurry. This supplies `_HIDPI` times the
    pixels inside a container of the intended width. Static files are resized once
    and cached; byte strings (uploads) are resized on every call.
    """
    try:
        if isinstance(source, bytes):
            data = resize_to_max_width(source, width * _HIDPI)
        else:
            data = _thumb_bytes(
                str(source), Path(source).stat().st_mtime_ns, width * _HIDPI
            )
    except OSError, ValueError:
        st.caption("_(image unavailable)_")
        return
    with st.container(width=width):
        st.image(data, caption=caption, alt=alt, width="stretch")


def current_user() -> str:
    return st.session_state["user_name"]


def is_admin() -> bool:
    return bool(st.session_state.get(_ADMIN_KEY))


def require_admin(settings: AppSettings, key: str) -> bool:
    """Render a passcode prompt unless already signed in as admin."""
    if is_admin():
        return True
    passcode = st.text_input("Instructor passcode", type="password", key=key)
    if not passcode:
        return False
    if passcode != settings.instructor_passcode:
        st.error("Incorrect passcode.")
        return False
    st.session_state[_ADMIN_KEY] = True
    st.rerun()
    return True  # unreachable; st.rerun() raises


def sign_out() -> None:
    st.session_state.pop("user_name", None)
    st.session_state.pop(_ADMIN_KEY, None)


def model_caption(settings: AppSettings, slug: str | None, seed: int | None) -> None:
    """One-line caption: model display name (+ seed when known)."""
    if not slug:
        return
    text = f":material/neurology: {md_escape(display_name(settings.models_path, slug))}"
    if seed is not None:
        text += f" · :material/casino: seed {seed}"
    st.caption(text)


def prompt_caption(prompt: str, key: str) -> None:
    """Show a (truncated) prompt as literal text; full text in a popover."""
    short = truncate(prompt, _PROMPT_PREVIEW_CHARS)
    st.caption(md_escape(short))
    if short != " ".join(prompt.split()):
        with st.popover(
            "Full prompt", type="tertiary", icon=":material/notes:", key=key
        ):
            st.text(prompt)
