from __future__ import annotations

import sqlite3
from pathlib import Path

import streamlit as st

from genai_cv_game.config import AppSettings
from genai_cv_game.db import (
    create_vote,
    get_active_round,
    get_submissions_for_round,
    get_vote_counts,
    update_submission_status,
)
from genai_cv_game.generation import poll_generation
from genai_cv_game.models import Round, Submission

# Gallery is wrapped in an st.fragment so the 5s auto-refresh only reruns this
# section. The student submission form and instructor sidebar are NOT rebuilt,
# which means in-flight generations and typed inputs are not disturbed.
_GALLERY_REFRESH_SECONDS = 5


@st.fragment(run_every=_GALLERY_REFRESH_SECONDS)
def render_gallery(settings: AppSettings) -> None:
    active = get_active_round(settings.db_path)
    if active is None:
        return

    st.divider()
    st.subheader("Gallery")

    if not active.gallery_revealed:
        st.info(
            "The gallery is hidden. The instructor will reveal the results "
            "after all teams have submitted."
        )
        return

    submissions = get_submissions_for_round(settings.db_path, active.id)
    _drain_pending(submissions, settings)
    submissions = get_submissions_for_round(settings.db_path, active.id)
    completed = [s for s in submissions if s.status == "completed"]
    failed = [s for s in submissions if s.status == "failed"]

    if active.mode == "match":
        _render_target_image(active)

    voter_name = _render_voter_input(active) if active.voting_open else ""

    if not completed:
        st.write("No submissions yet.")
    else:
        vote_counts = get_vote_counts(settings.db_path, active.id)
        _render_submission_grid(completed, active, vote_counts, voter_name, settings)

    if failed:
        _render_failed_submissions(failed)


def _drain_pending(submissions: list[Submission], settings: AppSettings) -> None:
    """Poll every pending submission so the gallery reflects the latest state."""
    for sub in submissions:
        if sub.status != "pending" or not sub.prediction_id:
            continue
        result = poll_generation(sub.prediction_id, sub.round_id, sub.id, settings)
        if result.status == "succeeded" and result.image_path:
            update_submission_status(
                settings.db_path, sub.id, "completed", image_path=result.image_path
            )
        elif result.status == "failed":
            update_submission_status(
                settings.db_path,
                sub.id,
                "failed",
                error_message=result.error or "Generation failed.",
            )


def _render_voter_input(round: Round) -> str:
    name = st.text_input(
        "Your name (to vote)",
        key=f"voter_name_{round.id}",
        help="Used once per round to record your vote.",
    )
    return name.strip()


def _render_target_image(round: Round) -> None:
    if round.target_image_path:
        path = Path(round.target_image_path)
        if path.exists():
            st.image(str(path), caption="Target image", width=400)


def _render_submission_grid(
    submissions: list[Submission],
    round: Round,
    vote_counts: dict[str, int],
    voter_name: str,
    settings: AppSettings,
) -> None:
    cols = st.columns(3)
    for i, sub in enumerate(submissions):
        _render_submission_card(
            sub, round, vote_counts, voter_name, settings, cols[i % 3]
        )


def _render_submission_card(
    sub: Submission,
    round: Round,
    vote_counts: dict[str, int],
    voter_name: str,
    settings: AppSettings,
    col: st.delta_generator.DeltaGenerator,
) -> None:
    with col:
        if sub.image_path and Path(sub.image_path).exists():
            st.image(sub.image_path, use_container_width=True)
        else:
            st.markdown("_(image unavailable)_")
        st.markdown(f"**{sub.team_name}**")
        if round.prompts_revealed:
            st.caption(sub.prompt)
        count = vote_counts.get(sub.id, 0)
        if round.voting_open or count > 0:
            label = f"Votes: **{count}**"
            if round.voting_open:
                label += " _(voting open)_"
            st.markdown(label)
        if round.voting_open:
            _render_vote_button(sub, round, voter_name, settings)


def _render_vote_button(
    sub: Submission, round: Round, voter_name: str, settings: AppSettings
) -> None:
    disabled = not voter_name
    if st.button(
        "Vote",
        key=f"vote_{sub.id}",
        disabled=disabled,
        help="Enter your name above to enable voting." if disabled else None,
    ):
        try:
            create_vote(settings.db_path, round.id, sub.id, voter_name)
            st.success("Vote recorded!")
        except sqlite3.IntegrityError:
            st.warning("You have already voted in this round.")


def _render_failed_submissions(failed: list[Submission]) -> None:
    with st.expander(f"Failed submissions ({len(failed)})"):
        for s in failed:
            st.markdown(f"- **{s.team_name}**: {s.error_message or 'Unknown error'}")
