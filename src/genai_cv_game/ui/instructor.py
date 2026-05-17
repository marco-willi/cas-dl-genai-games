from __future__ import annotations

from datetime import datetime, timezone

import streamlit as st

from genai_cv_game.config import AppSettings, ensure_directories
from genai_cv_game.db import (
    delete_database,
    delete_submission,
    get_active_round,
    get_all_rounds,
    get_submissions_for_round,
    reset_round_submissions,
    set_active_round,
    update_round_state,
)
from genai_cv_game.models import Round, Submission
from genai_cv_game.rounds import sync_rounds_from_json
from genai_cv_game.storage import clear_generated_dir, export_submissions_csv


def render_instructor_panel(settings: AppSettings) -> None:
    with st.sidebar:
        st.header("Instructor Panel")
        passcode = st.text_input("Passcode", type="password", key="instructor_passcode")
        if passcode != settings.instructor_passcode:
            if passcode:
                st.error("Incorrect passcode.")
            return
        _render_controls(settings)


def _render_controls(settings: AppSettings) -> None:
    all_rounds = get_all_rounds(settings.db_path)
    active = get_active_round(settings.db_path)

    if not all_rounds:
        st.warning("No rounds loaded.")
        return

    st.success("Instructor access granted.")
    _render_round_selector(all_rounds, active, settings)

    if active:
        _render_submission_counter(active, settings)
        st.divider()
        _render_state_toggles(active, settings)
        st.divider()
        _render_pending_submissions(active, settings)
        st.divider()
        _render_reset(active, settings)
        st.divider()
        _render_export(active, settings)

    st.divider()
    _render_danger_zone(settings)


def _render_round_selector(
    all_rounds: list[Round],
    active: Round | None,
    settings: AppSettings,
) -> None:
    st.subheader("Active Round")
    options = {r.id: r.title for r in all_rounds}
    current_id = active.id if active else all_rounds[0].id
    selected_id = st.selectbox(
        "Select round",
        options=list(options.keys()),
        format_func=lambda rid: options[rid],
        index=list(options.keys()).index(current_id),
        key="round_selector",
    )
    if selected_id != current_id:
        set_active_round(settings.db_path, selected_id)
        st.rerun()


def _render_state_toggles(active: Round, settings: AppSettings) -> None:
    st.subheader("Round Controls")
    flags = [
        ("submissions_open", "Submissions open"),
        ("gallery_revealed", "Gallery revealed"),
        ("prompts_revealed", "Prompts revealed"),
        ("voting_open", "Voting open"),
    ]
    for key, label in flags:
        current = getattr(active, key)
        new_val = st.toggle(label, value=current, key=f"toggle_{key}")
        if new_val != current:
            update_round_state(settings.db_path, active.id, **{key: new_val})
            st.rerun()


def _render_submission_counter(active: Round, settings: AppSettings) -> None:
    submissions = get_submissions_for_round(settings.db_path, active.id)
    completed = sum(1 for s in submissions if s.status == "completed")
    failed = sum(1 for s in submissions if s.status == "failed")
    pending = sum(1 for s in submissions if s.status == "pending")
    st.metric("Submissions", completed, help=f"{pending} pending · {failed} failed")


def _render_pending_submissions(active: Round, settings: AppSettings) -> None:
    pending = [
        s
        for s in get_submissions_for_round(settings.db_path, active.id)
        if s.status == "pending"
    ]
    if not pending:
        return
    with st.expander(f"Pending submissions ({len(pending)})", expanded=False):
        st.caption(
            "Submissions still generating. Clearing a row frees the team name "
            "so the team can submit again."
        )
        for sub in pending:
            _render_pending_row(sub, settings)


def _render_pending_row(sub: Submission, settings: AppSettings) -> None:
    col_name, col_age, col_action = st.columns([3, 2, 1])
    col_name.markdown(f"**{sub.team_name}**")
    col_age.caption(_relative_age(sub.updated_at))
    if col_action.button("Clear", key=f"clear_pending_{sub.id}"):
        delete_submission(settings.db_path, sub.id)
        st.rerun()


def _relative_age(ts: str) -> str:
    try:
        when = datetime.fromisoformat(ts)
    except ValueError:
        return ""
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    secs = int((datetime.now(timezone.utc) - when).total_seconds())
    if secs < 60:
        return f"{secs}s ago"
    if secs < 3600:
        return f"{secs // 60}m ago"
    return f"{secs // 3600}h ago"


def _render_reset(active: Round, settings: AppSettings) -> None:
    st.subheader("Reset Round")
    confirmed = st.checkbox(
        "I want to delete all submissions for this round",
        key="reset_confirm",
    )
    if st.button("Reset", disabled=not confirmed, type="secondary"):
        reset_round_submissions(settings.db_path, active.id)
        st.success("Round reset.")
        st.rerun()


def _render_export(active: Round, settings: AppSettings) -> None:
    st.subheader("Export")
    csv_bytes = export_submissions_csv(
        settings.db_path, active.id, round_title=active.title
    )
    st.download_button(
        label="Download submissions CSV",
        data=csv_bytes,
        file_name=f"{active.id}_submissions.csv",
        mime="text/csv",
    )


_DB_WIPE_CONFIRM = "DELETE"


def _render_danger_zone(settings: AppSettings) -> None:
    st.subheader(":red[Danger zone]")
    with st.expander("Delete entire database", expanded=False):
        st.warning(
            "This deletes the SQLite database **and every generated image**. "
            "Rounds will be re-loaded from `rounds.json` on the next render. "
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
    sync_rounds_from_json(settings.rounds_path, settings.db_path)
