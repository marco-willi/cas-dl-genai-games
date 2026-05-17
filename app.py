import streamlit as st

from genai_cv_game.config import ensure_directories, load_settings
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

    render_instructor_panel(settings)
    render_student_view(settings)
    render_gallery(settings)


if __name__ == "__main__":
    main()
