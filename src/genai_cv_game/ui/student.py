from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import streamlit as st

from genai_cv_game.config import AppSettings
from genai_cv_game.db import (
    DuplicateSubmissionError,
    create_submission,
    delete_submission,
    get_active_round,
    get_submissions_for_round,
    set_submission_prediction,
    update_submission_status,
)
from genai_cv_game.generation import poll_generation, start_generation
from genai_cv_game.models import Round, Submission

# Max time a submission may sit in 'pending' before we declare the generation
# dead. Replicate predictions usually finish in <60s; ample margin protects
# in-flight jobs from a concurrent rerun.
_PENDING_TIMEOUT_SECONDS = 180
# How often the student's "still generating" message re-polls the prediction.
_STUDENT_POLL_SECONDS = 3


def render_student_view(settings: AppSettings) -> None:
    active = get_active_round(settings.db_path)

    if active is None:
        st.info("No active round. Wait for the instructor.")
        return

    st.header(active.title)
    st.write(active.description)

    if active.mode == "match":
        _render_target_image(active, settings)

    if not active.submissions_open:
        st.warning(
            "Submissions are currently closed. Wait for the instructor to open the round."
        )
        return

    _render_submission_form(active, settings)


def _render_target_image(round: Round, settings: AppSettings) -> None:
    if round.target_image_path:
        path = Path(round.target_image_path)
        if path.exists():
            st.image(str(path), caption="Target image — recreate this with your prompt")
            st.caption(
                "Try to recreate the target image using text only. Do not describe "
                "the image too generally; include subject, composition, style, "
                "lighting, camera perspective, and important details."
            )
        else:
            st.warning("Target image is not available.")


def _get_team_submission(
    db_path: Path, round_id: str, team_name: str
) -> Submission | None:
    needle = team_name.strip().lower()
    for s in get_submissions_for_round(db_path, round_id):
        if s.team_name.lower() == needle:
            return s
    return None


def _pending_age_seconds(sub: Submission) -> float:
    try:
        updated = datetime.fromisoformat(sub.updated_at)
    except ValueError:
        return 0.0
    if updated.tzinfo is None:
        updated = updated.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - updated).total_seconds()


def _reconcile_pending(sub: Submission, settings: AppSettings) -> Submission:
    """Resolve a pending submission by polling or recovering from disk.

    Priority:
      1. If the row has a prediction_id, poll the generation backend.
      2. Else, if the image file already exists on disk, treat as completed.
      3. Else, if older than the timeout, mark failed.
      4. Else, leave pending — caller should show "still generating".
    """
    if sub.prediction_id:
        result = poll_generation(sub.prediction_id, sub.round_id, sub.id, settings)
        if result.status == "succeeded" and result.image_path:
            update_submission_status(
                settings.db_path, sub.id, "completed", image_path=result.image_path
            )
            return sub.model_copy(
                update={"status": "completed", "image_path": result.image_path}
            )
        if result.status == "failed":
            msg = result.error or "Generation failed."
            update_submission_status(
                settings.db_path, sub.id, "failed", error_message=msg
            )
            return sub.model_copy(update={"status": "failed", "error_message": msg})
        # status == "pending": fall through to age check below
    else:
        # Legacy / interrupted-start path: image may already be on disk.
        image_path = Path(settings.generated_dir) / sub.round_id / f"{sub.id}.png"
        if image_path.exists():
            update_submission_status(
                settings.db_path, sub.id, "completed", image_path=str(image_path)
            )
            return sub.model_copy(
                update={"status": "completed", "image_path": str(image_path)}
            )

    if _pending_age_seconds(sub) > _PENDING_TIMEOUT_SECONDS:
        msg = "Generation timed out. Please try again."
        update_submission_status(settings.db_path, sub.id, "failed", error_message=msg)
        return sub.model_copy(update={"status": "failed", "error_message": msg})
    return sub


def _render_submission_form(round: Round, settings: AppSettings) -> None:
    team_name = st.text_input("Team name", key="team_name")
    prompt = st.text_area("Your prompt", key="prompt")

    existing = (
        _get_team_submission(settings.db_path, round.id, team_name)
        if team_name
        else None
    )

    if existing and existing.status == "pending":
        _render_pending_status(existing, settings)
        return

    if existing and existing.status == "completed":
        st.success("You have already submitted for this round.")
        if existing.image_path:
            st.image(existing.image_path)
        return

    if existing and existing.status == "failed":
        st.error(f"Your previous submission failed: {existing.error_message}")
        if st.button("Try again", key=f"retry_{existing.id}"):
            delete_submission(settings.db_path, existing.id)
            st.rerun()
        return

    disabled = not team_name.strip() or not prompt.strip()
    if st.button("Generate", disabled=disabled):
        _handle_submission(round, team_name.strip(), prompt.strip(), settings)


@st.fragment(run_every=_STUDENT_POLL_SECONDS)
def _render_pending_status(sub: Submission, settings: AppSettings) -> None:
    """Auto-polling block for a team's in-flight submission.

    Reruns every few seconds inside its own fragment so the user sees the
    result appear without having to click anything, but the surrounding form
    inputs stay intact.
    """
    refreshed = _reconcile_pending(sub, settings)
    if refreshed.status == "pending":
        st.info(
            "Your submission is still generating. This usually takes 10–60 seconds…"
        )
        return
    # Status changed — bounce the full page so the parent form re-renders
    # with the completed/failed branch.
    st.rerun(scope="app")


def _handle_submission(
    round: Round, team_name: str, prompt: str, settings: AppSettings
) -> None:
    try:
        sub_id = create_submission(settings.db_path, round.id, team_name, prompt)
    except DuplicateSubmissionError as e:
        st.warning(str(e))
        return

    try:
        prediction_id = start_generation(prompt, round.id, sub_id, settings)
        set_submission_prediction(settings.db_path, sub_id, prediction_id)
    except Exception as e:
        update_submission_status(
            settings.db_path, sub_id, "failed", error_message=str(e)
        )
        st.error(f"Could not start generation: {e}")
        return

    # Rerun so the parent form sees the new pending row and switches to the
    # auto-polling fragment.
    st.rerun()
