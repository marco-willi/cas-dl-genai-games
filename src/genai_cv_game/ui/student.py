from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import streamlit as st

from genai_cv_game.config import AppSettings
from genai_cv_game.db import (
    DuplicateSubmissionError,
    MaxAttemptsReachedError,
    choose_submission,
    create_submission,
    delete_submission,
    get_active_round,
    get_team_submissions,
    set_submission_prediction,
    update_submission_status,
)
from genai_cv_game.generation import poll_generation, start_generation
from genai_cv_game.model_catalog import find_model, load_enabled_models
from genai_cv_game.models import ModelEntry, Round, Submission

# Max time a draft may sit in 'pending' before we declare the generation
# dead and let the team retry.
_PENDING_TIMEOUT_SECONDS = 180
# How often the "still generating" block re-polls the prediction.
_STUDENT_POLL_SECONDS = 3


def render_student_view(settings: AppSettings) -> None:
    active = get_active_round(settings.db_path)

    if active is None:
        st.info("No active round. Wait for the instructor.")
        return

    st.header(active.title)
    st.write(active.description)

    if active.mode == "match":
        _render_target_image(active)

    if not active.submissions_open:
        st.warning(
            "Submissions are currently closed. Wait for the instructor to open the round."
        )
        return

    _render_team_workspace(active, settings)


# ── Round-level helpers ─────────────────────────────────────────────────────


def _render_target_image(round: Round) -> None:
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


# ── Team workspace (top-level form) ─────────────────────────────────────────


def _render_team_workspace(round: Round, settings: AppSettings) -> None:
    team_name = st.session_state["user_name"]

    team_rows = get_team_submissions(settings.db_path, round.id, team_name)
    chosen = next((s for s in team_rows if s.is_chosen), None)
    if chosen:
        _render_submitted(chosen)
        return

    drafts = [_reconcile_submission(s, settings) for s in team_rows]
    has_in_flight = any(d.status == "pending" for d in drafts)

    if drafts:
        st.subheader(f"Your candidates ({len(drafts)} / {settings.max_attempts})")
        _render_drafts_grid(drafts, settings, locked=has_in_flight)

    if has_in_flight:
        _render_in_flight_notice(round, team_name, settings)
        return

    if len(drafts) >= settings.max_attempts:
        st.warning(
            f"You have used all {settings.max_attempts} attempts. Pick one of "
            "your candidates above to submit, or clear an attempt to free a slot."
        )
        return

    _render_prompt_form(round, team_name, drafts, settings)


def _render_submitted(submission: Submission) -> None:
    st.success("You have submitted this round.")
    if submission.image_path and Path(submission.image_path).exists():
        st.image(submission.image_path)
    st.caption(f"Prompt: {submission.prompt}")


# ── Draft rendering ─────────────────────────────────────────────────────────


def _render_drafts_grid(
    drafts: list[Submission], settings: AppSettings, locked: bool
) -> None:
    cols = st.columns(min(3, max(1, len(drafts))))
    for i, draft in enumerate(drafts):
        with cols[i % len(cols)]:
            _render_draft_card(draft, settings, locked=locked)


def _render_draft_card(draft: Submission, settings: AppSettings, locked: bool) -> None:
    if draft.status == "completed" and draft.image_path:
        st.image(draft.image_path, width="stretch")
    elif draft.status == "pending":
        st.markdown("⏳ _generating…_")
    else:  # failed
        st.markdown("⚠️ _failed_")

    if draft.model_slug:
        st.caption(f"🧠 {_pretty_model(draft.model_slug, settings)}")
    st.caption(draft.prompt)

    if draft.status == "failed":
        st.error(draft.error_message or "Generation failed.")
        if st.button("Discard", key=f"discard_{draft.id}"):
            delete_submission(settings.db_path, draft.id)
            st.rerun()
        return

    if draft.status == "completed":
        if st.button(
            "Use this",
            key=f"use_{draft.id}",
            type="primary",
            disabled=locked,
            help="Submit this candidate to the gallery." if not locked else None,
        ):
            _handle_use_this(draft, settings)
        if st.button(
            "Discard",
            key=f"discard_{draft.id}",
            disabled=locked,
            help="Free this attempt slot." if not locked else None,
        ):
            delete_submission(settings.db_path, draft.id)
            st.rerun()


def _handle_use_this(draft: Submission, settings: AppSettings) -> None:
    try:
        choose_submission(settings.db_path, draft.id)
    except DuplicateSubmissionError as e:
        st.warning(str(e))
        return
    except ValueError as e:
        st.error(str(e))
        return
    st.success("Submitted to the gallery!")
    st.rerun()


# ── Prompt form (next attempt) ──────────────────────────────────────────────


def _render_prompt_form(
    round: Round, team_name: str, drafts: list[Submission], settings: AppSettings
) -> None:
    remaining = settings.max_attempts - len(drafts)
    next_num = len(drafts) + 1
    default_prompt = drafts[-1].prompt if drafts else ""
    default_model_slug = drafts[-1].model_slug if drafts else None

    st.subheader(f"Attempt {next_num} of {settings.max_attempts}")
    st.caption(
        f"{remaining} attempt{'s' if remaining != 1 else ''} remaining. "
        "Tweak the prompt or change the model to try a new variation."
    )

    model = _render_model_selector(
        round, settings, next_num, preferred_slug=default_model_slug
    )
    _render_prompt_tips()
    prompt = st.text_area(
        "Your prompt",
        value=default_prompt,
        key=f"prompt_{round.id}_{next_num}",
    )

    disabled = not prompt.strip() or model is None
    if st.button("Generate", disabled=disabled, key=f"gen_{round.id}_{next_num}"):
        _handle_new_attempt(round, team_name, prompt.strip(), model, settings)


def _render_model_selector(
    round: Round,
    settings: AppSettings,
    next_num: int,
    preferred_slug: str | None,
) -> ModelEntry | None:
    """Show the catalog dropdown. Returns the chosen ModelEntry (or None).

    None is returned only when the catalog is empty AND stub mode is off AND
    no DEFAULT_REPLICATE_MODEL fallback exists — in which case the caller
    disables Generate. In stub mode we return None silently (stub ignores it).
    """
    enabled = load_enabled_models(settings.models_path)
    if not enabled:
        if settings.use_stub_generation or settings.default_replicate_model:
            st.caption("Using the default model (no catalog configured).")
            return None
        st.error(
            "No image generation models are enabled. Ask the instructor to "
            "enable a model in the sidebar."
        )
        return None

    default_index = 0
    if preferred_slug:
        for i, m in enumerate(enabled):
            if m.slug == preferred_slug:
                default_index = i
                break

    chosen_slug = st.selectbox(
        "Model",
        options=[m.slug for m in enabled],
        format_func=lambda slug: next(
            m.display_name for m in enabled if m.slug == slug
        ),
        index=default_index,
        key=f"model_{round.id}_{next_num}",
    )
    chosen = next(m for m in enabled if m.slug == chosen_slug)
    if chosen.description:
        st.caption(chosen.description)
    return chosen


def _handle_new_attempt(
    round: Round,
    team_name: str,
    prompt: str,
    model: ModelEntry | None,
    settings: AppSettings,
) -> None:
    slug = model.slug if model else None
    try:
        submission_id = create_submission(
            settings.db_path,
            round.id,
            team_name,
            prompt,
            settings.max_attempts,
            model_slug=slug,
        )
    except MaxAttemptsReachedError as e:
        st.warning(str(e))
        return
    except DuplicateSubmissionError as e:
        st.warning(str(e))
        return
    try:
        prediction_id = start_generation(
            prompt, round.id, submission_id, settings, model_slug=slug
        )
        set_submission_prediction(settings.db_path, submission_id, prediction_id)
    except Exception as e:
        update_submission_status(
            settings.db_path, submission_id, "failed", error_message=str(e)
        )
        st.error(f"Could not start generation: {e}")
        return
    st.rerun()


# ── In-flight polling (auto-refresh while pending) ──────────────────────────


@st.fragment(run_every=_STUDENT_POLL_SECONDS)
def _render_in_flight_notice(
    round: Round, team_name: str, settings: AppSettings
) -> None:
    drafts = [
        s
        for s in get_team_submissions(settings.db_path, round.id, team_name)
        if not s.is_chosen
    ]
    still_pending = any(
        _reconcile_submission(d, settings).status == "pending" for d in drafts
    )

    if still_pending:
        st.info("A candidate is still generating. This usually takes 10–60 seconds…")
        return
    st.rerun(scope="app")


def _reconcile_submission(draft: Submission, settings: AppSettings) -> Submission:
    """Resolve a pending draft by polling or recovering from disk."""
    if draft.status != "pending":
        return draft

    if draft.prediction_id:
        result = poll_generation(
            draft.prediction_id, draft.round_id, draft.id, settings
        )
        if result.status == "succeeded" and result.image_path:
            update_submission_status(
                settings.db_path,
                draft.id,
                "completed",
                image_path=result.image_path,
            )
            return draft.model_copy(
                update={"status": "completed", "image_path": result.image_path}
            )
        if result.status == "failed":
            msg = result.error or "Generation failed."
            update_submission_status(
                settings.db_path, draft.id, "failed", error_message=msg
            )
            return draft.model_copy(update={"status": "failed", "error_message": msg})
    else:
        image_path = Path(settings.generated_dir) / draft.round_id / f"{draft.id}.png"
        if image_path.exists():
            update_submission_status(
                settings.db_path,
                draft.id,
                "completed",
                image_path=str(image_path),
            )
            return draft.model_copy(
                update={"status": "completed", "image_path": str(image_path)}
            )

    if _pending_age_seconds(draft) > _PENDING_TIMEOUT_SECONDS:
        msg = "Generation timed out. Please try again."
        update_submission_status(
            settings.db_path, draft.id, "failed", error_message=msg
        )
        return draft.model_copy(update={"status": "failed", "error_message": msg})
    return draft


def _pending_age_seconds(draft: Submission) -> float:
    try:
        updated = datetime.fromisoformat(draft.updated_at)
    except ValueError:
        return 0.0
    if updated.tzinfo is None:
        updated = updated.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - updated).total_seconds()


def _render_prompt_tips() -> None:
    with st.expander("Prompt tips"):
        st.markdown(
            """
            A strong prompt usually names most of these explicitly:

            - **Subject** — what is in the frame (and what is not)
            - **Composition** — placement, framing, perspective
            - **Style** — photographic, illustration, 3D render, painterly, etc.
            - **Lighting** — soft / harsh, direction, time of day
            - **Camera** — lens (e.g. 35 mm, 85 mm), depth of field, angle
            - **Mood & colour palette** — warm/cool, dominant colours
            - **Details that matter** — text on signage, materials, textures

            Iterate: start broad, then add one constraint at a time and re-run.
            """
        )


def _pretty_model(slug: str, settings: AppSettings) -> str:
    """Return the catalog display name for a slug, or the slug if unknown."""
    model = find_model(settings.models_path, slug)
    return model.display_name if model else slug
