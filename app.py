import streamlit as st

from genai_cv_game.config import AppSettings, ensure_directories, load_settings
from genai_cv_game.rounds import sync_rounds_from_json
from genai_cv_game.ui.gallery import render_gallery
from genai_cv_game.ui.instructor import render_instructor_panel
from genai_cv_game.ui.student import render_student_view


def main() -> None:
    settings = load_settings()
    ensure_directories(settings)
    sync_rounds_from_json(settings.rounds_path, settings.db_path)

    st.set_page_config(page_title=settings.app_title, layout="wide")
    st.title(settings.app_title)

    if not _ensure_logged_in(settings):
        return

    _render_user_bar()
    render_instructor_panel(settings)
    render_student_view(settings)
    render_gallery(settings)


def _ensure_logged_in(settings: AppSettings) -> bool:
    if st.session_state.get("user_name"):
        return True

    st.subheader("Sign in")
    st.caption(
        "Your name is used as both your team name (for submissions) and your "
        "voter name. Pick something your classmates will recognise."
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


def _render_user_bar() -> None:
    user = st.session_state["user_name"]
    cols = st.columns([6, 1])
    cols[0].caption(f"Signed in as **{user}**")
    if cols[1].button("Sign out", key="sign_out"):
        st.session_state.pop("user_name", None)
        st.rerun()


if __name__ == "__main__":
    main()
