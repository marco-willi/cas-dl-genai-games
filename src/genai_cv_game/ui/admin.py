from __future__ import annotations

import streamlit as st

from genai_cv_game.config import AppSettings, ensure_directories
from genai_cv_game.db import (
    delete_database,
    get_all_tasks,
    is_api_enabled,
    reset_all_generations,
    reset_task_generations,
    set_api_enabled,
    set_task_availability,
)
from genai_cv_game.models import Task
from genai_cv_game.storage import (
    clear_generated_dir,
    clear_task_generated_dir,
    export_gallery_csv,
)
from genai_cv_game.tasks import sync_tasks_from_json


def render_admin_page(settings: AppSettings) -> None:
    st.header("Admin Panel")
    if not st.session_state.get("admin_authenticated"):
        passcode = st.text_input("Passcode", type="password", key="admin_passcode")
        if not passcode:
            return
        if passcode != settings.instructor_passcode:
            st.error("Incorrect passcode.")
            return
        st.session_state["admin_authenticated"] = True
        st.rerun()
    _render_controls(settings)


def _render_controls(settings: AppSettings) -> None:
    tasks = get_all_tasks(settings.db_path)
    st.success("Admin access granted.")

    _render_api_switch(settings)
    st.divider()
    if not tasks:
        st.warning("No tasks loaded.")
    else:
        _render_availability(tasks, settings)
        st.divider()
        _render_gallery_resets(tasks, settings)
        st.divider()
        _render_export(tasks, settings)
    st.divider()
    _render_danger_zone(settings)


def _render_api_switch(settings: AppSettings) -> None:
    st.subheader("Generation API")
    current = is_api_enabled(settings.db_path)
    new_val = st.toggle("API enabled", value=current, key="toggle_api_enabled")
    if new_val != current:
        set_api_enabled(settings.db_path, new_val)
        st.rerun()
    st.caption(
        "When off, students cannot start new generations. Viewing the gallery "
        "and in-flight generations are unaffected."
    )


def _render_availability(tasks: list[Task], settings: AppSettings) -> None:
    st.subheader("Task availability")
    st.caption("Only available tasks appear in the student task picker.")
    for task in tasks:
        new_val = st.toggle(
            task.title,
            value=task.is_available,
            key=f"toggle_avail_{task.id}",
        )
        if new_val != task.is_available:
            set_task_availability(settings.db_path, task.id, new_val)
            st.rerun()


def _render_gallery_resets(tasks: list[Task], settings: AppSettings) -> None:
    st.subheader("Gallery resets")
    st.caption(
        "Resetting deletes all generations (and image files) for the task — "
        "this clears the gallery and frees students' budgets. There is no undo."
    )

    options = {t.id: t.title for t in tasks}
    selected_id = st.selectbox(
        "Task to reset",
        options=list(options.keys()),
        format_func=lambda tid: options[tid],
        key="reset_task_select",
    )
    confirm_one = st.checkbox(
        "Confirm reset of this task", key="reset_task_confirm"
    )
    if st.button(
        "Reset this task", disabled=not confirm_one, type="secondary"
    ):
        reset_task_generations(settings.db_path, selected_id)
        clear_task_generated_dir(settings.generated_dir, selected_id)
        st.success(f"Reset gallery for '{options[selected_id]}'.")
        st.rerun()

    st.markdown("---")
    confirm_all = st.checkbox(
        "Confirm reset of ALL tasks", key="reset_all_confirm"
    )
    if st.button(
        "Reset ALL galleries", disabled=not confirm_all, type="secondary"
    ):
        reset_all_generations(settings.db_path)
        clear_generated_dir(settings.generated_dir)
        st.success("All galleries reset.")
        st.rerun()


def _render_export(tasks: list[Task], settings: AppSettings) -> None:
    st.subheader("Export")
    options = {t.id: t.title for t in tasks}
    selected_id = st.selectbox(
        "Task to export",
        options=list(options.keys()),
        format_func=lambda tid: options[tid],
        key="export_task_select",
    )
    csv_bytes = export_gallery_csv(
        settings.db_path, selected_id, task_title=options[selected_id]
    )
    st.download_button(
        label="Download gallery CSV",
        data=csv_bytes,
        file_name=f"{selected_id}_gallery.csv",
        mime="text/csv",
    )


_DB_WIPE_CONFIRM = "DELETE"


def _render_danger_zone(settings: AppSettings) -> None:
    st.subheader(":red[Danger zone]")
    with st.expander("Delete entire database", expanded=False):
        st.warning(
            "This deletes the SQLite database **and every generated image**. "
            "Tasks will be re-loaded from `tasks.json` on the next render. "
            "There is no undo."
        )
        typed = st.text_input(
            f"Type `{_DB_WIPE_CONFIRM}` to enable the button",
            key="db_wipe_confirm",
        )
        disabled = typed.strip() != _DB_WIPE_CONFIRM
        if st.button(
            "Delete database and generated images",
            type="primary",
            disabled=disabled,
            key="db_wipe_button",
        ):
            _wipe_everything(settings)
            st.success("Database and generated images deleted.")
            st.rerun()


def _wipe_everything(settings: AppSettings) -> None:
    delete_database(settings.db_path)
    clear_generated_dir(settings.generated_dir)
    ensure_directories(settings)
    sync_tasks_from_json(settings.tasks_path, settings.db_path)
