from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import streamlit as st

from genai_cv_game.config import AppSettings
from genai_cv_game.db import (
    BudgetReachedError,
    create_generation,
    delete_generation,
    get_user_generations,
    is_api_enabled,
    remove_from_gallery,
    set_generation_prediction,
    submit_to_gallery,
    update_generation_status,
)
from genai_cv_game.generation import poll_generation, start_generation
from genai_cv_game.model_catalog import find_model, load_enabled_models
from genai_cv_game.models import Generation, ModelEntry, Task
from genai_cv_game.ui.gallery import render_gallery

# Max time a generation may sit in 'pending' before we declare it dead.
_PENDING_TIMEOUT_SECONDS = 180
# How often the "still generating" block re-polls the prediction.
_STUDENT_POLL_SECONDS = 3
# Task modes that pass source/cut-out images to the image-generation model.
_IMAGE_INPUT_MODES = frozenset({"edit", "compose"})


def render_task_page(settings: AppSettings, task: Task) -> None:
    """Render one task's page: a Generate tab and a Gallery tab."""
    tab_generate, tab_gallery = st.tabs(["Generate", "Gallery"])

    with tab_generate:
        st.header(task.title)
        st.write(task.description)

        if task.mode == "match":
            _render_target_image(task)
        elif task.mode in _IMAGE_INPUT_MODES:
            _render_input_images(task)

        _render_user_workspace(task, settings)

    with tab_gallery:
        render_gallery(settings, task)


# ── Task-level helpers ───────────────────────────────────────────────────────


def _render_target_image(task: Task) -> None:
    if task.target_image_path:
        path = Path(task.target_image_path)
        if path.exists():
            st.image(str(path), caption="Target image — recreate this with your prompt")
            st.caption(
                "Try to recreate the target image using text only. Do not describe "
                "the image too generally; include subject, composition, style, "
                "lighting, camera perspective, and important details."
            )
        else:
            st.warning("Target image is not available.")


def _render_input_images(task: Task) -> None:
    if not task.input_image_paths:
        st.warning("This task has no input images configured.")
        return

    if task.mode == "edit":
        caption = "Source image — edit this with your prompt."
        tip = (
            "Describe the change you want to apply. Be specific about what should "
            "stay the same (subject, layout, text) and what should change "
            "(lighting, style, background, time of day, weather, …)."
        )
    else:  # compose
        caption = "Object — place this into a scene generated from your prompt."
        tip = (
            "Describe the scene that surrounds the object. Match lighting and "
            "perspective in your prompt so the result looks coherent. The object "
            "should remain the visual hero of the image."
        )

    missing = [p for p in task.input_image_paths if not Path(p).exists()]
    available = [p for p in task.input_image_paths if Path(p).exists()]

    if available:
        cols = st.columns(min(3, len(available)))
        for i, p in enumerate(available):
            with cols[i % len(cols)]:
                st.image(p, caption=caption if i == 0 else None)
        st.caption(tip)
    if missing:
        st.warning(
            f"{len(missing)} input image(s) not available: " + ", ".join(missing)
        )


# ── User workspace ───────────────────────────────────────────────────────────


def _render_user_workspace(task: Task, settings: AppSettings) -> None:
    user_name = st.session_state["user_name"]

    rows = get_user_generations(settings.db_path, task.id, user_name)
    generations = [_reconcile_generation(g, settings) for g in rows]
    has_in_flight = any(g.status == "pending" for g in generations)
    live_count = sum(1 for g in generations if g.status != "failed")

    if generations:
        st.subheader(f"Your generations ({live_count} / {settings.generation_budget})")
        _render_generations_grid(generations, settings, locked=has_in_flight)

    if has_in_flight:
        _render_in_flight_notice(task, user_name, settings)
        return

    if not is_api_enabled(settings.db_path):
        st.info("Image generation is currently paused by the admin.")
        return

    if live_count >= settings.generation_budget:
        st.warning(
            f"You have used all {settings.generation_budget} generations for this "
            "task. Pick one of your results to show in the gallery, or discard a "
            "failed attempt to free a slot."
        )
        return

    _render_prompt_form(task, user_name, generations, settings)


# ── Generation cards ─────────────────────────────────────────────────────────


def _render_generations_grid(
    generations: list[Generation], settings: AppSettings, locked: bool
) -> None:
    cols = st.columns(min(3, max(1, len(generations))))
    for i, gen in enumerate(generations):
        with cols[i % len(cols)]:
            _render_generation_card(gen, settings, locked=locked)


def _render_generation_card(
    gen: Generation, settings: AppSettings, locked: bool
) -> None:
    if gen.status == "completed" and gen.image_path:
        st.image(gen.image_path, width="stretch")
    elif gen.status == "pending":
        st.markdown("⏳ _generating…_")
    else:  # failed
        st.markdown("⚠️ _failed_")

    if gen.model_slug:
        st.caption(f"🧠 {_pretty_model(gen.model_slug, settings)}")
    st.caption(gen.prompt)

    if gen.status == "failed":
        st.error(gen.error_message or "Generation failed.")
        if st.button("Discard", key=f"discard_{gen.id}"):
            delete_generation(settings.db_path, gen.id)
            st.rerun()
        return

    if gen.status != "completed":
        return

    if gen.in_gallery:
        st.success("Shown in the gallery")
        if st.button(
            "Remove from gallery",
            key=f"remove_{gen.id}",
            disabled=locked,
        ):
            remove_from_gallery(settings.db_path, gen.id)
            st.rerun()
    else:
        if st.button(
            "Show in gallery",
            key=f"show_{gen.id}",
            type="primary",
            disabled=locked,
            help="Make this your gallery entry for the task." if not locked else None,
        ):
            _handle_show_in_gallery(gen, settings)


def _handle_show_in_gallery(gen: Generation, settings: AppSettings) -> None:
    try:
        submit_to_gallery(settings.db_path, gen.id)
    except ValueError as e:
        st.error(str(e))
        return
    st.success("Added to the gallery!")
    st.rerun()


# ── Prompt form (next generation) ────────────────────────────────────────────


def _render_prompt_form(
    task: Task, user_name: str, generations: list[Generation], settings: AppSettings
) -> None:
    live_count = sum(1 for g in generations if g.status != "failed")
    remaining = settings.generation_budget - live_count
    next_num = live_count + 1
    default_prompt = generations[-1].prompt if generations else ""
    default_model_slug = generations[-1].model_slug if generations else None

    st.subheader(f"Generation {next_num} of {settings.generation_budget}")
    st.caption(
        f"{remaining} generation{'s' if remaining != 1 else ''} remaining. "
        "Tweak the prompt or change the model to try a new variation."
    )

    model = _render_model_selector(
        task, settings, next_num, preferred_slug=default_model_slug
    )
    _render_prompt_tips()
    prompt = st.text_area(
        "Your prompt",
        value=default_prompt,
        key=f"prompt_{task.id}_{next_num}",
    )

    disabled = (
        not prompt.strip()
        or model is None
        or (task.mode in _IMAGE_INPUT_MODES and not _resolve_input_image_paths(task))
    )
    if st.button("Generate", disabled=disabled, key=f"gen_{task.id}_{next_num}"):
        _handle_new_generation(task, user_name, prompt.strip(), model, settings)


def _render_model_selector(
    task: Task,
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
    if task.mode in _IMAGE_INPUT_MODES:
        enabled = [m for m in enabled if m.supports_image_input]
    if not enabled:
        if task.mode in _IMAGE_INPUT_MODES:
            st.error(
                "This task needs an image-input model, but none are enabled. "
                "Ask the admin to enable a model with "
                "`supports_image_input: true` in `data/models.json`."
            )
            return None
        if settings.use_stub_generation or settings.default_replicate_model:
            st.caption("Using the default model (no catalog configured).")
            return None
        st.error(
            "No image generation models are enabled. Ask the admin to "
            "enable a model in `data/models.json`."
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
        key=f"model_{task.id}_{next_num}",
    )
    chosen = next(m for m in enabled if m.slug == chosen_slug)
    if chosen.description:
        st.caption(chosen.description)
    return chosen


def _handle_new_generation(
    task: Task,
    user_name: str,
    prompt: str,
    model: ModelEntry | None,
    settings: AppSettings,
) -> None:
    slug = model.slug if model else None
    image_paths: list[Path] | None = None
    if task.mode in _IMAGE_INPUT_MODES:
        image_paths = _resolve_input_image_paths(task)
        if not image_paths:
            st.error(
                "This task's input images are not available on disk. "
                "Ask the admin to add them to `assets/input_images/`."
            )
            return
    try:
        generation_id = create_generation(
            settings.db_path,
            task.id,
            user_name,
            prompt,
            settings.generation_budget,
            model_slug=slug,
        )
    except BudgetReachedError as e:
        st.warning(str(e))
        return
    try:
        prediction_id = start_generation(
            prompt,
            task.id,
            generation_id,
            settings,
            model_slug=slug,
            image_input_paths=image_paths,
        )
        set_generation_prediction(settings.db_path, generation_id, prediction_id)
    except Exception as e:
        update_generation_status(
            settings.db_path, generation_id, "failed", error_message=str(e)
        )
        st.error(f"Could not start generation: {e}")
        return
    st.rerun()


def _resolve_input_image_paths(task: Task) -> list[Path]:
    return [Path(p) for p in task.input_image_paths if Path(p).exists()]


# ── In-flight polling (auto-refresh while pending) ──────────────────────────


@st.fragment(run_every=_STUDENT_POLL_SECONDS)
def _render_in_flight_notice(
    task: Task, user_name: str, settings: AppSettings
) -> None:
    rows = get_user_generations(settings.db_path, task.id, user_name)
    still_pending = any(
        _reconcile_generation(g, settings).status == "pending" for g in rows
    )

    if still_pending:
        st.info("A generation is still running. This usually takes 10–60 seconds…")
        return
    st.rerun(scope="app")


def _reconcile_generation(gen: Generation, settings: AppSettings) -> Generation:
    """Resolve a pending generation by polling or recovering from disk."""
    if gen.status != "pending":
        return gen

    if gen.prediction_id:
        result = poll_generation(gen.prediction_id, gen.task_id, gen.id, settings)
        if result.status == "succeeded" and result.image_path:
            update_generation_status(
                settings.db_path,
                gen.id,
                "completed",
                image_path=result.image_path,
            )
            return gen.model_copy(
                update={"status": "completed", "image_path": result.image_path}
            )
        if result.status == "failed":
            msg = result.error or "Generation failed."
            update_generation_status(
                settings.db_path, gen.id, "failed", error_message=msg
            )
            return gen.model_copy(update={"status": "failed", "error_message": msg})
    else:
        image_path = Path(settings.generated_dir) / gen.task_id / f"{gen.id}.png"
        if image_path.exists():
            update_generation_status(
                settings.db_path,
                gen.id,
                "completed",
                image_path=str(image_path),
            )
            return gen.model_copy(
                update={"status": "completed", "image_path": str(image_path)}
            )

    if _pending_age_seconds(gen) > _PENDING_TIMEOUT_SECONDS:
        msg = "Generation timed out. Please try again."
        update_generation_status(settings.db_path, gen.id, "failed", error_message=msg)
        return gen.model_copy(update={"status": "failed", "error_message": msg})
    return gen


def _pending_age_seconds(gen: Generation) -> float:
    try:
        updated = datetime.fromisoformat(gen.updated_at)
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
