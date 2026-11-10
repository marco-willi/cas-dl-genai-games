"""Instructor-only projector view: one task's gallery or vote results, big."""

from __future__ import annotations

import streamlit as st

from genai_cv_game.config import AppSettings
from genai_cv_game.db import get_all_tasks
from genai_cv_game.ui.common import require_admin
from genai_cv_game.ui.gallery import render_projector_gallery
from genai_cv_game.ui.vote import render_vote_results

_RESULTS_REFRESH_SECONDS = 5


def render_projector_page(settings: AppSettings) -> None:
    if not require_admin(settings, key="projector_passcode"):
        st.caption("The projector view is for the instructor.")
        return
    tasks = get_all_tasks(settings.db_path)
    if not tasks:
        st.warning("No tasks loaded.")
        return
    by_id = {t.id: t for t in tasks}
    task_id = st.selectbox(
        "Show",
        options=list(by_id),
        format_func=lambda tid: by_id[tid].title,
        key="projector_task",
        label_visibility="collapsed",
    )
    task = by_id[task_id]
    st.title(task.title)
    if task.mode == "vote":
        _vote_results(settings, task.id)
    else:
        render_projector_gallery(settings, task)


@st.fragment(run_every=_RESULTS_REFRESH_SECONDS)
def _vote_results(settings: AppSettings, task_id: str) -> None:
    render_vote_results(settings, task_id, user_name=None)
