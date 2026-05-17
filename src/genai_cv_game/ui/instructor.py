from __future__ import annotations

from datetime import datetime, timezone

import streamlit as st

from genai_cv_game.config import AppSettings, ensure_directories
from genai_cv_game.db import (
    delete_database,
    delete_team_submissions,
    get_active_round,
    get_all_rounds,
    get_submissions_for_round,
    reset_round_submissions,
    set_active_round,
    update_round_state,
)
from genai_cv_game.models import Round
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
    _render_models_info(settings)
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
    drafting_teams = _list_drafting_teams(active.id, settings)
    st.metric(
        "Submitted",
        len(submissions),
        help=f"{len(drafting_teams)} team(s) still drafting candidates",
    )


def _list_drafting_teams(round_id: str, settings: AppSettings) -> list[dict]:
    """Return drafting-team summaries: name, draft counts, latest update.

    Drafting teams are those with at least one draft (is_chosen=0) row and
    no chosen row yet.
    """
    from genai_cv_game.db import get_connection

    with get_connection(settings.db_path) as conn:
        rows = conn.execute(
            """
            SELECT team_name,
                   COUNT(*)                              AS total,
                   SUM(status='pending')                 AS pending,
                   SUM(status='completed')               AS completed,
                   SUM(status='failed')                  AS failed,
                   MAX(updated_at)                       AS last_update
            FROM submissions
            WHERE round_id=? AND is_chosen=0
            GROUP BY LOWER(team_name)
            ORDER BY last_update DESC
            """,
            (round_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def _render_pending_submissions(active: Round, settings: AppSettings) -> None:
    drafting = _list_drafting_teams(active.id, settings)
    if not drafting:
        return
    with st.expander(f"Teams still drafting ({len(drafting)})", expanded=False):
        st.caption(
            "Teams generating candidates but not yet submitted. Clearing a "
            "team's attempts frees their slot so they can start fresh."
        )
        for d in drafting:
            _render_drafting_row(d, active, settings)


def _render_drafting_row(team: dict, active: Round, settings: AppSettings) -> None:
    col_name, col_status, col_action = st.columns([3, 3, 1])
    col_name.markdown(f"**{team['team_name']}**")
    parts = [f"{team['completed']} ready"]
    if team["pending"]:
        parts.append(f"{team['pending']} ⏳")
    if team["failed"]:
        parts.append(f"{team['failed']} ⚠️")
    parts.append(_relative_age(team["last_update"]))
    col_status.caption(" · ".join(parts))
    safe_key = team["team_name"].replace(" ", "_").lower()
    if col_action.button("Clear", key=f"clear_attempts_{active.id}_{safe_key}"):
        delete_team_submissions(settings.db_path, active.id, team["team_name"])
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


def _render_models_info(settings: AppSettings) -> None:
    st.subheader("Available Models")
    from genai_cv_game.model_catalog import load_models

    models = load_models(settings.models_path)
    if not models:
        st.caption(
            "No models in the catalog. Edit `data/models.json` and restart "
            "the app to populate it."
        )
        return
    st.caption(
        f"Edit `{settings.models_path}` (set `is_enabled: false`) and restart "
        "to change what students may pick."
    )
    for m in models:
        marker = "✅" if m.is_enabled else "🚫"
        st.markdown(f"{marker} **{m.display_name}** — `{m.slug}`")


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
