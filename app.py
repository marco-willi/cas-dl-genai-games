from functools import partial

import streamlit as st

from genai_cv_game.config import AppSettings, ensure_directories, load_settings
from genai_cv_game.db import get_available_tasks
from genai_cv_game.tasks import sync_tasks_from_json
from genai_cv_game.ui.admin import render_admin_page
from genai_cv_game.ui.student import render_task_page


def main() -> None:
    settings = load_settings()
    ensure_directories(settings)
    sync_tasks_from_json(settings.tasks_path, settings.db_path)

    st.set_page_config(page_title=settings.app_title, layout="wide")

    if not _ensure_logged_in(settings):
        return

    tasks = get_available_tasks(settings.db_path)
    task_pages = [
        st.Page(
            partial(render_task_page, settings, task),
            title=task.title,
            url_path=task.id,
        )
        for task in tasks
    ]
    admin_page = st.Page(
        partial(render_admin_page, settings),
        title="Admin",
        url_path="admin",
    )

    pages: dict[str, list] = {"Admin": [admin_page]}
    if task_pages:
        pages = {"Tasks": task_pages, "Admin": [admin_page]}

    pg = st.navigation(pages)
    _render_sidebar(tasks)
    pg.run()


def _ensure_logged_in(settings: AppSettings) -> bool:
    if st.session_state.get("user_name"):
        return True

    st.title(settings.app_title)
    st.subheader("Sign in")
    st.caption(
        "Your name identifies your generations and gallery entries. Pick "
        "something your classmates will recognise."
    )
    with st.form("login"):
        name = st.text_input("Your name")
        passcode = st.text_input("Class passcode", type="password")
        ok = st.form_submit_button("Enter")
    if not ok:
        return False
    name = name.strip()
    if not name:
        st.error("Please enter a name.")
        return False
    if passcode != settings.app_passcode:
        st.error("Incorrect passcode.")
        return False
    st.session_state["user_name"] = name
    st.rerun()
    return False


def _render_sidebar(tasks: list) -> None:
    with st.sidebar:
        if not tasks:
            st.info("No tasks are available yet. Check back later.")
        st.divider()
        user = st.session_state["user_name"]
        st.caption(f"Signed in as **{user}**")
        if st.button("Sign out", key="sign_out"):
            st.session_state.pop("user_name", None)
            st.session_state.pop("admin_authenticated", None)
            st.rerun()


if __name__ == "__main__":
    main()
