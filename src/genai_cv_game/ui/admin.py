from __future__ import annotations

import streamlit as st

from genai_cv_game.config import (
    MAX_GENERATION_BUDGET,
    AppSettings,
    ensure_directories,
)
from genai_cv_game.db import (
    delete_database,
    get_all_tasks,
    get_budget_override,
    get_class_stats,
    is_api_enabled,
    is_vote_revealed,
    reset_all_generations,
    reset_all_votes,
    reset_task_generations,
    reset_task_votes,
    set_api_enabled,
    set_budget_override,
    set_task_availability,
    set_vote_revealed,
)
from genai_cv_game.models import Task
from genai_cv_game.service import generation_budget
from genai_cv_game.storage import (
    clear_generated_dir,
    clear_task_generated_dir,
    export_gallery_csv,
    export_votes_csv,
)
from genai_cv_game.tasks import sync_tasks_from_json
from genai_cv_game.ui.common import require_admin

_DB_WIPE_CONFIRM = "DELETE"


def render_admin_page(settings: AppSettings) -> None:
    st.header("Admin")
    if not require_admin(settings, key="admin_passcode"):
        return
    st.caption(
        "While you are signed in as admin, every gallery card shows a **Hide** "
        "button for removing an inappropriate entry."
    )
    tasks = get_all_tasks(settings.db_path)

    _render_stats(settings)
    _render_api_switch(settings)
    _render_budget(settings)
    if tasks:
        _render_vote_reveal(tasks, settings)
        _render_availability(tasks, settings)
        _render_resets(tasks, settings)
        _render_export(tasks, settings)
    else:
        st.warning("No tasks loaded.")
    _render_danger_zone(settings)


@st.fragment(run_every=10)
def _render_stats(settings: AppSettings) -> None:
    s = get_class_stats(settings.db_path)
    with st.container(horizontal=True):
        st.metric("Participants", s.participants, border=True)
        st.metric(
            "Generations", s.generations, border=True, help=f"{s.pending} running now"
        )
        st.metric("Failed", s.failed, border=True)
        st.metric(
            "Avg. time to image",
            f"{s.avg_seconds:.0f} s" if s.avg_seconds is not None else "—",
            border=True,
        )


def _render_api_switch(settings: AppSettings) -> None:
    with st.container(border=True):
        st.subheader("Generation API")
        current = is_api_enabled(settings.db_path)
        new_val = st.toggle(
            "Students can generate images", value=current, key="toggle_api_enabled"
        )
        if new_val != current:
            set_api_enabled(settings.db_path, new_val)
            st.rerun()
        st.caption(
            "When off, students cannot start new generations. The gallery and "
            "generations already running are unaffected."
        )


def _render_budget(settings: AppSettings) -> None:
    with st.container(border=True):
        st.subheader("Generation budget")
        current = generation_budget(settings)
        override = get_budget_override(settings.db_path)
        source = (
            "set here" if override is not None else "default from `GENERATION_BUDGET`"
        )
        st.caption(
            f"Each student may make **{current} generations per task** ({source}). "
            "Changes apply to all tasks immediately; students who hit the old limit "
            "can continue right away. Lowering it never deletes results — students "
            "above the new limit just can't generate more."
        )
        with st.container(horizontal=True, vertical_alignment="bottom"):
            new_budget = st.number_input(
                "Generations per task",
                min_value=1,
                max_value=MAX_GENERATION_BUDGET,
                value=current,
                step=5,
                key="budget_input",
            )
            if st.button(
                "Apply",
                key="budget_apply",
                type="primary",
                icon=":material/check:",
                disabled=int(new_budget) == current,
            ):
                set_budget_override(settings.db_path, int(new_budget))
                st.toast(f"Budget set to {int(new_budget)} generations per task.")
                st.rerun()
            if override is not None and st.button(
                f"Reset to default ({settings.generation_budget})",
                key="budget_reset",
                icon=":material/restart_alt:",
            ):
                set_budget_override(settings.db_path, None)
                st.session_state.pop("budget_input", None)
                st.rerun()


def _render_vote_reveal(tasks: list[Task], settings: AppSettings) -> None:
    vote_tasks = [t for t in tasks if t.mode == "vote"]
    if not vote_tasks:
        return
    with st.container(border=True):
        st.subheader("Vote games")
        st.caption(
            "Reveal the true labels, scores and hints. Revealing also closes voting; "
            "hide again to reopen it."
        )
        for task in vote_tasks:
            current = is_vote_revealed(settings.db_path, task.id)
            new_val = st.toggle(
                f"Reveal results: {task.short_title}",
                value=current,
                key=f"reveal_{task.id}",
            )
            if new_val != current:
                set_vote_revealed(settings.db_path, task.id, new_val)
                st.rerun()


def _render_availability(tasks: list[Task], settings: AppSettings) -> None:
    with st.container(border=True):
        st.subheader("Task availability")
        st.caption("Only available tasks appear in the students' navigation.")
        for task in tasks:
            new_val = st.toggle(
                task.title, value=task.is_available, key=f"toggle_avail_{task.id}"
            )
            if new_val != task.is_available:
                set_task_availability(settings.db_path, task.id, new_val)
                st.rerun()


def _render_resets(tasks: list[Task], settings: AppSettings) -> None:
    with st.container(border=True):
        st.subheader("Data resets")
        st.caption(
            "Resetting clears all data for the task — generations, likes and image "
            "files (freeing students' budgets), or the votes and the reveal state "
            "for vote games. There is no undo."
        )
        options = {t.id: t.title for t in tasks}
        selected_id = st.selectbox(
            "Task to reset",
            options=list(options),
            format_func=options.__getitem__,
            key="reset_task_select",
        )
        confirm_one = st.checkbox(
            "Confirm reset of this task", key="reset_task_confirm"
        )
        if st.button("Reset this task", disabled=not confirm_one):
            _reset_task(settings, selected_id)
            st.toast(f"Reset data for '{options[selected_id]}'.")
            st.rerun()

        st.divider()
        confirm_all = st.checkbox("Confirm reset of ALL tasks", key="reset_all_confirm")
        if st.button("Reset ALL tasks", disabled=not confirm_all):
            reset_all_generations(settings.db_path)
            reset_all_votes(settings.db_path)
            for t in tasks:
                set_vote_revealed(settings.db_path, t.id, False)
            clear_generated_dir(settings.generated_dir)
            st.toast("All task data reset.")
            st.rerun()


def _reset_task(settings: AppSettings, task_id: str) -> None:
    reset_task_generations(settings.db_path, task_id)
    reset_task_votes(settings.db_path, task_id)
    set_vote_revealed(settings.db_path, task_id, False)
    clear_task_generated_dir(settings.generated_dir, task_id)


def _render_export(tasks: list[Task], settings: AppSettings) -> None:
    with st.container(border=True):
        st.subheader("Export")
        by_id = {t.id: t for t in tasks}
        selected_id = st.selectbox(
            "Task to export",
            options=list(by_id),
            format_func=lambda tid: by_id[tid].title,
            key="export_task_select",
        )
        task = by_id[selected_id]
        if task.mode == "vote":
            data, label, suffix = (
                export_votes_csv(settings.db_path, task.id, task_title=task.title),
                "Download vote results CSV",
                "votes",
            )
        else:
            data, label, suffix = (
                export_gallery_csv(settings.db_path, task.id, task_title=task.title),
                "Download gallery CSV",
                "gallery",
            )
        st.download_button(
            label=label,
            data=data,
            file_name=f"{task.id}_{suffix}.csv",
            mime="text/csv",
            icon=":material/download:",
        )


def _render_danger_zone(settings: AppSettings) -> None:
    st.subheader(":red[Danger zone]")
    with st.expander("Delete entire database", icon=":material/warning:"):
        st.warning(
            "This deletes the SQLite database **and every generated image**. "
            "Tasks are re-loaded from `tasks.json`. There is no undo."
        )
        typed = st.text_input(
            f"Type `{_DB_WIPE_CONFIRM}` to enable the button", key="db_wipe_confirm"
        )
        if st.button(
            "Delete database and generated images",
            type="primary",
            disabled=typed.strip() != _DB_WIPE_CONFIRM,
            key="db_wipe_button",
        ):
            delete_database(settings.db_path)
            clear_generated_dir(settings.generated_dir)
            ensure_directories(settings)
            sync_tasks_from_json(settings.tasks_path, settings.db_path)
            st.toast("Database and generated images deleted.")
            st.rerun()
