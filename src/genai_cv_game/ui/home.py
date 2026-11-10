"""Landing page: what today looks like, how the game works, privacy note."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import streamlit as st
from streamlit.navigation.page import StreamlitPage

from genai_cv_game.config import AppSettings
from genai_cv_game.service import generation_budget
from genai_cv_game.ui.common import PRIVACY_NOTE, current_user
from genai_cv_game.utils import md_escape


def render_home_page(
    settings: AppSettings, sections: Mapping[str, Sequence[StreamlitPage]]
) -> None:
    """`sections` maps a section title to its task pages (as in st.navigation)."""
    st.title(settings.app_title)
    st.markdown(
        f"Welcome, **{md_escape(current_user())}**! Today you'll get hands-on with "
        "generative image models: spot fakes, write prompts, edit images, push "
        "models until they fail, and compare them side by side."
    )

    with st.container(horizontal=True):
        for icon, title, body in (
            (
                ":material/route:",
                "Pick a task",
                "Tasks are grouped in the sidebar. New ones unlock during class.",
            ),
            (
                ":material/auto_awesome:",
                "Generate",
                (
                    f"You get **{generation_budget(settings)} generations per task**. "
                    "Failed attempts don't count."
                ),
            ),
            (
                ":material/photo_library:",
                "Share & like",
                "Put your best result in the task gallery and like your classmates' work.",
            ),
        ):
            with st.container(border=True):
                st.markdown(f"#### {icon} {title}")
                st.markdown(body)

    st.subheader("Today's tasks")
    for section, pages in sections.items():
        if not pages:
            continue
        st.markdown(f"**{section}**")
        with st.container(horizontal=True):
            for page in pages:
                st.page_link(page)

    st.info(PRIVACY_NOTE, title="Privacy", icon=":material/shield:")
