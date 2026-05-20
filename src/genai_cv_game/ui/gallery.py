from __future__ import annotations

from pathlib import Path

import streamlit as st

from genai_cv_game.config import AppSettings
from genai_cv_game.db import get_gallery_generations
from genai_cv_game.model_catalog import find_model
from genai_cv_game.models import Generation, Task

# Gallery is wrapped in an st.fragment so the auto-refresh only reruns this
# section, leaving the student workspace and admin sidebar untouched.
_GALLERY_REFRESH_SECONDS = 5


def render_gallery(settings: AppSettings, task: Task | None) -> None:
    if task is None:
        return
    _render_gallery_fragment(settings, task.id)


@st.fragment(run_every=_GALLERY_REFRESH_SECONDS)
def _render_gallery_fragment(settings: AppSettings, task_id: str) -> None:
    from genai_cv_game.db import get_task

    task = get_task(settings.db_path, task_id)
    if task is None:
        return

    st.caption("Generations classmates have chosen to share for this task.")

    generations = get_gallery_generations(settings.db_path, task.id)
    completed = [g for g in generations if g.status == "completed"]

    if not completed:
        st.write("No gallery entries yet. Be the first to share one!")
        return

    _render_gallery_grid(completed, task, settings)


def _render_gallery_grid(
    generations: list[Generation],
    task: Task,
    settings: AppSettings,
) -> None:
    # Match mode gets a 2-col grid so each card has room for target + result
    # side by side. Other modes keep the denser 3-col layout.
    grid_width = 2 if task.mode == "match" else 3
    cols = st.columns(grid_width)
    for i, gen in enumerate(generations):
        _render_gallery_card(gen, task, settings, cols[i % grid_width])


def _render_gallery_card(
    gen: Generation,
    task: Task,
    settings: AppSettings,
    col: st.delta_generator.DeltaGenerator,
) -> None:
    with col:
        if task.mode == "match" and _target_path(task):
            _render_match_pair(task, gen)
        else:
            _render_generation_image(gen)
        st.markdown(f"**{gen.user_name}**")
        if gen.model_slug:
            model = find_model(settings.models_path, gen.model_slug)
            label = model.display_name if model else gen.model_slug
            st.caption(f"🧠 {label}")
        st.caption(gen.prompt)


def _target_path(task: Task) -> Path | None:
    if not task.target_image_path:
        return None
    p = Path(task.target_image_path)
    return p if p.exists() else None


def _render_match_pair(task: Task, gen: Generation) -> None:
    target = _target_path(task)
    target_col, gen_col = st.columns(2)
    with target_col:
        st.image(str(target), caption="Target", width="stretch")
    with gen_col:
        if gen.image_path and Path(gen.image_path).exists():
            st.image(gen.image_path, caption="Result", width="stretch")
        else:
            st.markdown("_(image unavailable)_")


def _render_generation_image(gen: Generation) -> None:
    if gen.image_path and Path(gen.image_path).exists():
        st.image(gen.image_path, width="stretch")
    else:
        st.markdown("_(image unavailable)_")
