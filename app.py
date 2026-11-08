from functools import partial

import streamlit as st
from dotenv import load_dotenv

from genai_cv_game.config import AppSettings, ensure_directories, load_settings
from genai_cv_game.db import get_available_tasks
from genai_cv_game.models import Task
from genai_cv_game.tasks import sync_tasks_from_json
from genai_cv_game.ui.admin import render_admin_page
from genai_cv_game.ui.common import MODE_ICONS, PRIVACY_NOTE, sign_out
from genai_cv_game.ui.home import render_home_page
from genai_cv_game.ui.projector import render_projector_page
from genai_cv_game.ui.student import render_task_page
from genai_cv_game.utils import md_escape

_DEFAULT_SECTION = "Tasks"


@st.cache_resource(show_spinner=False)
def _bootstrap(settings_json: str, tasks_mtime_ns: int, db_exists: bool) -> None:
    """Create directories and sync tasks.json into the DB once per process.

    Re-runs automatically when tasks.json changes or the DB file disappears
    (both are part of the cache key). Doing this on every rerun cost ~250 ms per click. The admin's
    "delete database" action re-syncs explicitly.
    """
    settings = AppSettings.model_validate_json(settings_json)
    ensure_directories(settings)
    sync_tasks_from_json(settings.tasks_path, settings.db_path)


def main() -> None:
    load_dotenv()
    settings = load_settings()
    _bootstrap(
        settings.model_dump_json(),
        settings.tasks_path.stat().st_mtime_ns,
        settings.db_path.exists(),
    )

    st.set_page_config(
        page_title=settings.app_title, page_icon=":material/palette:", layout="wide"
    )

    if not _ensure_logged_in(settings):
        return

    tasks = get_available_tasks(settings.db_path)
    sections = _task_sections(settings, tasks)
    home = st.Page(
        partial(render_home_page, settings, sections),
        title="Home",
        icon=":material/home:",
        url_path="home",
        default=True,
    )
    instructor = [
        st.Page(
            partial(render_admin_page, settings),
            title="Admin",
            icon=":material/admin_panel_settings:",
            url_path="admin",
        ),
        st.Page(
            partial(render_projector_page, settings),
            title="Projector",
            icon=":material/present_to_all:",
            url_path="projector",
        ),
    ]
    pg = st.navigation(
        {"": [home], **sections, "Instructor": instructor}, expanded=True
    )
    _render_sidebar(has_tasks=bool(tasks))
    pg.run()


def _task_sections(settings: AppSettings, tasks: list[Task]) -> dict[str, list]:
    """Group task pages by their `section` (tasks.json order is kept)."""
    sections: dict[str, list] = {}
    for task in tasks:
        page = st.Page(
            partial(render_task_page, settings, task),
            title=task.short_title,
            icon=task.icon or MODE_ICONS.get(task.mode),
            url_path=task.id,
        )
        sections.setdefault(task.section or _DEFAULT_SECTION, []).append(page)
    return sections


def _ensure_logged_in(settings: AppSettings) -> bool:
    if st.session_state.get("user_name"):
        return True

    _, center, _ = st.columns([1, 2, 1])
    with center:
        st.title(settings.app_title)
        st.markdown(
            "Spot fakes, write prompts, edit images and compare models — a "
            "hands-on day with generative AI for computer vision."
        )
        with st.form("login", border=True):
            name = st.text_input(
                "Your name",
                help="Shown next to your gallery entries. Pick something your "
                "classmates will recognise — and reuse it if you reload the page.",
            )
            passcode = st.text_input("Class passcode", type="password")
            ok = st.form_submit_button("Enter", type="primary", icon=":material/login:")
        st.caption(f":material/shield: {PRIVACY_NOTE}")
    if not ok:
        return False
    name = " ".join(name.split())
    if not name:
        center.error("Please enter a name.")
        return False
    if passcode != settings.app_passcode:
        center.error("Incorrect passcode.")
        return False
    st.session_state["user_name"] = name
    st.rerun()
    return False


def _render_sidebar(has_tasks: bool) -> None:
    with st.sidebar:
        if not has_tasks:
            st.info("No tasks are available yet. Check back later.")
        st.divider()
        st.caption(
            f":material/person: Signed in as **{md_escape(st.session_state['user_name'])}**"
        )
        if st.button(
            "Sign out", key="sign_out", icon=":material/logout:", type="tertiary"
        ):
            sign_out()
            st.rerun()


if __name__ == "__main__":
    main()
