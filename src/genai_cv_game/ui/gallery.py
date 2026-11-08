"""Per-task gallery: shared results, likes, admin moderation, projector view."""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from genai_cv_game.config import AppSettings
from genai_cv_game.db import (
    get_gallery_generations,
    get_reaction_counts,
    get_task,
    get_user_reactions,
    hide_from_gallery,
    toggle_reaction,
)
from genai_cv_game.models import Generation, Task
from genai_cv_game.ui.common import (
    asset_image,
    current_user,
    is_admin,
    model_caption,
    prompt_caption,
)
from genai_cv_game.utils import md_escape

# Only this fragment reruns on the timer, leaving the rest of the page alone.
_GALLERY_REFRESH_SECONDS = 5


def render_gallery(settings: AppSettings, task: Task) -> None:
    _render_gallery_fragment(settings, task.id, projector=False)


def render_projector_gallery(settings: AppSettings, task: Task) -> None:
    """Large, control-free gallery for the beamer."""
    _render_gallery_fragment(settings, task.id, projector=True)


@st.fragment(run_every=_GALLERY_REFRESH_SECONDS)
def _render_gallery_fragment(
    settings: AppSettings, task_id: str, projector: bool
) -> None:
    task = get_task(settings.db_path, task_id)
    if task is None:
        return

    entries = [
        g
        for g in get_gallery_generations(settings.db_path, task.id)
        if g.status == "completed"
    ]
    likes = get_reaction_counts(settings.db_path, task.id)
    top = max((likes.get(g.id, 0) for g in entries), default=0)

    if not projector:
        st.caption(
            "Results classmates chose to share. Like your favourites — the most "
            "liked entry becomes the class favourite."
        )
    if task.mode == "match":
        _render_target_strip(task)
    if not entries:
        st.info(
            "No gallery entries yet. Be the first to share one!",
            icon=":material/photo_library:",
        )
        return

    # One card per student; their picks (gallery_picks > 1) side by side.
    groups: dict[str, list[Generation]] = {}
    for g in entries:  # already ordered by created_at
        groups.setdefault(g.user_name.lower(), []).append(g)
    cards = list(groups.values())
    # Most-liked first on the projector; chronological for students.
    if projector:
        cards.sort(key=lambda c: max(likes.get(g.id, 0) for g in c), reverse=True)
    liked_by_me = (
        set()
        if projector
        else get_user_reactions(settings.db_path, task.id, current_user())
    )
    n_cols = 2 if projector or task.gallery_picks > 1 else 3
    cols = st.columns(n_cols)
    for i, card in enumerate(cards):
        with cols[i % n_cols]:
            _render_card(
                card,
                settings,
                likes=likes,
                top=top,
                liked_by_me=liked_by_me,
                projector=projector,
            )


def _render_target_strip(task: Task) -> None:
    path = Path(task.target_image_path) if task.target_image_path else None
    if path and path.exists():
        with st.expander("Target image", icon=":material/target:", expanded=True):
            st.image(asset_image(path) or str(path), width=360, alt="Target image")


def _render_card(
    picks: list[Generation],
    settings: AppSettings,
    likes: dict[str, int],
    top: int,
    liked_by_me: set[str],
    projector: bool,
) -> None:
    """One student's gallery entry: their shared pick(s), side by side."""
    owner = picks[0].user_name
    with st.container(border=True):
        with st.container(horizontal=True, vertical_alignment="center"):
            st.markdown(f"**{md_escape(owner)}**")
            if top > 0 and any(likes.get(g.id, 0) == top for g in picks):
                st.badge("Class favourite", icon=":material/trophy:", color="orange")
        if len(picks) == 1:
            _render_pick(picks[0], settings, likes, liked_by_me, projector, single=True)
            return
        for col, gen in zip(st.columns(len(picks)), picks, strict=True):
            with col:
                _render_pick(gen, settings, likes, liked_by_me, projector, single=False)


def _render_pick(
    gen: Generation,
    settings: AppSettings,
    likes: dict[str, int],
    liked_by_me: set[str],
    projector: bool,
    single: bool,
) -> None:
    result = (
        gen.image_path if gen.image_path and Path(gen.image_path).exists() else None
    )
    source = gen.input_image_path
    if single and result and source and Path(source).exists():
        # Edited images: show the original next to the result.
        before, after = st.columns(2)
        before.image(
            (asset_image(source) if source.startswith("assets/") else None) or source,
            caption="Before",
            width="stretch",
            alt="Original image",
        )
        after.image(result, caption="After", width="stretch", alt=gen.prompt[:200])
    elif result:
        st.image(result, width="stretch", alt=gen.prompt[:200])
    else:
        st.caption("_(image unavailable)_")

    n_likes = likes.get(gen.id, 0)
    model_caption(settings, gen.model_slug, gen.seed)
    if projector:
        st.badge(f"{n_likes}", icon=":material/thumb_up:", color="gray")
        st.caption(md_escape(gen.prompt))
        return
    prompt_caption(gen.prompt, key=f"gal_prompt_{gen.id}")

    with st.container(horizontal=True, gap="small"):
        own = gen.user_name.lower() == current_user().lower()
        if st.button(
            str(n_likes),
            key=f"like_{gen.id}",
            icon=":material/thumb_up:",
            type="primary" if gen.id in liked_by_me else "secondary",
            disabled=own,
            help="You can't like your own image." if own else "Like / unlike",
        ):
            try:
                toggle_reaction(settings.db_path, gen.id, current_user())
            except ValueError as e:
                st.toast(str(e))
            st.rerun(scope="fragment")
        if is_admin() and st.button(
            "Hide",
            key=f"hide_{gen.id}",
            icon=":material/visibility_off:",
            type="tertiary",
            help="Instructor only: remove this entry from the gallery. "
            "The student cannot share it again.",
        ):
            hide_from_gallery(settings.db_path, gen.id)
            st.rerun(scope="fragment")
