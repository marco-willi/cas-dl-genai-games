"""Generation workflow — the glue between DB, storage and the Replicate client.

Everything here is UI-free (no `st.*`), so it can be unit-tested directly. The
Streamlit pages call these functions and only render the outcome.
"""

from __future__ import annotations

import random
from collections.abc import Sequence
from pathlib import Path

from genai_cv_game.config import AppSettings
from genai_cv_game.db import (
    BudgetReachedError,
    create_generation,
    get_budget_override,
    get_user_generations,
    set_generation_input_image,
    set_generation_prediction,
    update_generation_status,
)
from genai_cv_game.generation import (
    DEFAULT_IMAGE_INPUT_FIELD,
    poll_generation,
    start_generation,
)
from genai_cv_game.models import (
    FIXED_INPUT_MODES,
    UPLOAD_INPUT_MODES,
    Generation,
    ModelEntry,
    Task,
)
from genai_cv_game.storage import make_submission_image_path, save_uploaded_input_image
from genai_cv_game.utils import new_id, seconds_since

__all__ = [
    "PENDING_TIMEOUT_SECONDS",
    "BudgetReachedError",
    "GenerationError",
    "generation_budget",
    "group_rounds",
    "input_label",
    "live_count",
    "pick_seed",
    "reconcile_generation",
    "reconcile_user_generations",
    "remaining_budget",
    "resolve_input_image_paths",
    "start_comparison_round",
    "start_single_generation",
]

# Max time a generation may sit in 'pending' before we declare it dead.
PENDING_TIMEOUT_SECONDS = 180
_SEED_MAX = 2**31 - 1


class GenerationError(Exception):
    """A generation could not be started; the message is safe to show."""


# ── Budget helpers ───────────────────────────────────────────────────────────


def generation_budget(settings: AppSettings) -> int:
    """Per-task budget in effect: the admin's override, else `GENERATION_BUDGET`."""
    override = get_budget_override(settings.db_path)
    return override if override is not None else settings.generation_budget


def live_count(generations: Sequence[Generation]) -> int:
    """Generations that count against the budget (pending + completed)."""
    return sum(1 for g in generations if g.status != "failed")


def remaining_budget(generations: Sequence[Generation], budget: int) -> int:
    return max(0, budget - live_count(generations))


def pick_seed(model: ModelEntry | None, requested: int | None) -> int | None:
    """Seed to send: the requested one, or a fresh random one, if supported.

    Always sending an explicit seed (instead of letting the model choose) means
    every result can be reproduced and shown to students.
    """
    if model is None or not model.supports_seed:
        return None
    return requested if requested is not None else random.randint(0, _SEED_MAX)


def resolve_input_image_paths(task: Task) -> list[Path]:
    return [Path(p) for p in task.input_image_paths if Path(p).exists()]


def input_label(path: str | Path) -> str:
    """Human label for a prepared input image, from its file name.

    `assets/input_images/refund/food_with_bite.jpg` -> "Food with bite".
    """
    return Path(path).stem.replace("_", " ").replace("-", " ").strip().capitalize()


# ── Starting generations ─────────────────────────────────────────────────────


def start_single_generation(
    settings: AppSettings,
    task: Task,
    user_name: str,
    prompt: str,
    model: ModelEntry | None,
    *,
    upload: bytes | None = None,
    prepared_input: str | None = None,
    seed: int | None = None,
) -> str:
    """Create a generation row and start its prediction. Returns its id.

    Source image by mode: fixed modes (edit/compose) use the task's images;
    upload modes (explore) use `upload`, or — if the task offers prepared
    images — one of them chosen via `prepared_input` (must be listed in the
    task's `input_image_paths`). The source is recorded on the row for
    before/after views.

    Raises `BudgetReachedError` when the budget is used up and
    `GenerationError` for missing inputs. A failure to start the prediction is
    recorded on the row (status `failed`) and re-raised as `GenerationError`.
    """
    image_paths: list[Path] | None = None
    if task.mode in FIXED_INPUT_MODES:
        image_paths = resolve_input_image_paths(task)
        if not image_paths:
            raise GenerationError(
                "This task's input images are not available on disk. "
                "Ask the instructor to add them to `assets/input_images/`."
            )
    if task.mode in UPLOAD_INPUT_MODES and upload is None:
        if prepared_input is None:
            raise GenerationError(
                "Please choose or upload an image to edit before generating."
            )
        if prepared_input not in task.input_image_paths:
            raise GenerationError("That image is not one of this task's options.")
        if not Path(prepared_input).exists():
            raise GenerationError(f"Prepared image is missing: {prepared_input}")
        image_paths = [Path(prepared_input)]

    seed = pick_seed(model, seed)
    generation_id = create_generation(
        settings.db_path,
        task.id,
        user_name,
        prompt,
        generation_budget(settings),
        model_slug=model.slug if model else None,
        seed=seed,
    )
    try:
        if upload is not None and task.mode in UPLOAD_INPUT_MODES:
            image_paths = [
                save_uploaded_input_image(
                    settings.generated_dir, task.id, generation_id, upload
                )
            ]
        if image_paths:
            set_generation_input_image(
                settings.db_path, generation_id, str(image_paths[0])
            )
        _start(settings, task, generation_id, prompt, model, image_paths, seed)
    except Exception as e:
        update_generation_status(
            settings.db_path, generation_id, "failed", error_message=str(e)
        )
        raise GenerationError(f"Could not start generation: {e}") from e
    return generation_id


def start_comparison_round(
    settings: AppSettings,
    task: Task,
    user_name: str,
    prompt: str,
    models: Sequence[ModelEntry],
    *,
    seed: int | None = None,
) -> tuple[int, list[str]]:
    """Fan one prompt out to several models as one round (shared `batch_id`).

    One model failing to start never aborts the rest; the budget is enforced
    per row. Models that support a seed all get the same one, so the round is
    reproducible. Returns (rows created, error messages).
    """
    batch_id = new_id()
    shared_seed = seed if seed is not None else random.randint(0, _SEED_MAX)
    created = 0
    errors: list[str] = []
    for model in models:
        model_seed = shared_seed if model.supports_seed else None
        try:
            generation_id = create_generation(
                settings.db_path,
                task.id,
                user_name,
                prompt,
                generation_budget(settings),
                model_slug=model.slug,
                seed=model_seed,
                batch_id=batch_id,
            )
        except BudgetReachedError as e:
            errors.append(str(e))
            break
        created += 1
        try:
            _start(settings, task, generation_id, prompt, model, None, model_seed)
        except Exception as e:
            update_generation_status(
                settings.db_path, generation_id, "failed", error_message=str(e)
            )
            errors.append(f"{model.display_name}: {e}")
    return created, errors


def _start(
    settings: AppSettings,
    task: Task,
    generation_id: str,
    prompt: str,
    model: ModelEntry | None,
    image_paths: list[Path] | None,
    seed: int | None,
) -> None:
    prediction_id = start_generation(
        prompt,
        task.id,
        generation_id,
        settings,
        model_slug=model.slug if model else None,
        image_input_paths=image_paths,
        image_input_field=model.image_input_field
        if model
        else DEFAULT_IMAGE_INPUT_FIELD,
        seed=seed,
    )
    set_generation_prediction(settings.db_path, generation_id, prediction_id)


# ── Reconciling pending generations ──────────────────────────────────────────


def reconcile_generation(gen: Generation, settings: AppSettings) -> Generation:
    """Resolve a pending generation by polling or recovering from disk.

    Persists any status change and returns the updated model.
    """
    if gen.status != "pending":
        return gen

    if gen.prediction_id:
        result = poll_generation(gen.prediction_id, gen.task_id, gen.id, settings)
        if result.status == "completed" and result.image_path:
            return _mark(gen, settings, "completed", image_path=result.image_path)
        if result.status == "failed":
            return _mark(
                gen,
                settings,
                "failed",
                error_message=result.error or "Generation failed.",
            )
    else:
        image_path = make_submission_image_path(
            settings.generated_dir, gen.task_id, gen.id
        )
        if image_path.exists():
            return _mark(gen, settings, "completed", image_path=str(image_path))

    if seconds_since(gen.updated_at) > PENDING_TIMEOUT_SECONDS:
        return _mark(
            gen,
            settings,
            "failed",
            error_message="Generation timed out. Please try again.",
        )
    return gen


def reconcile_user_generations(
    settings: AppSettings, task_id: str, user_name: str
) -> list[Generation]:
    """All of a user's generations on a task (oldest first), pending ones polled."""
    return [
        reconcile_generation(g, settings)
        for g in get_user_generations(settings.db_path, task_id, user_name)
    ]


def _mark(
    gen: Generation,
    settings: AppSettings,
    status: str,
    *,
    image_path: str | None = None,
    error_message: str | None = None,
) -> Generation:
    update_generation_status(
        settings.db_path,
        gen.id,
        status,
        image_path=image_path,
        error_message=error_message,
    )
    return gen.model_copy(
        update={
            "status": status,
            "image_path": image_path,
            "error_message": error_message,
        }
    )


# ── Presentation helpers ─────────────────────────────────────────────────────


def group_rounds(generations: Sequence[Generation]) -> list[list[Generation]]:
    """Group comparison generations into rounds (shared `batch_id`), newest first.

    Rows without a batch id (older data) each form their own round.
    """
    rounds: dict[str, list[Generation]] = {}
    for g in generations:
        rounds.setdefault(g.batch_id or g.id, []).append(g)
    return sorted(rounds.values(), key=lambda r: r[0].created_at, reverse=True)
