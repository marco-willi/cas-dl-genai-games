"""Image generation via Replicate, structured for async resumability.

Two-step flow:

1. `start_generation` — non-blocking. Creates a Replicate prediction (or, in
   stub mode, writes the placeholder image synchronously). Returns a string
   identifier that is persisted on the generation row.
2. `poll_generation` — checks whether the prediction has finished and, on
   success, downloads the image to disk. Called from the reconcile path in
   `service.py` on each rerun / fragment tick.

A stub prediction id has the form `stub:<generation_id>` so the poll path can
distinguish synchronous stub results from real Replicate predictions.
"""

from __future__ import annotations

import shutil
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path

import replicate

from genai_cv_game.config import AppSettings
from genai_cv_game.models import GenerationStatus
from genai_cv_game.storage import download_image, make_submission_image_path

_STUB_PREFIX = "stub:"
DEFAULT_IMAGE_INPUT_FIELD = "image_input"


@dataclass
class GenerationResult:
    status: GenerationStatus
    image_path: str | None = None
    error: str | None = None


def start_generation(
    prompt: str,
    task_id: str,
    generation_id: str,
    settings: AppSettings,
    model_slug: str | None = None,
    image_input_paths: list[Path] | None = None,
    image_input_field: str = DEFAULT_IMAGE_INPUT_FIELD,
    seed: int | None = None,
) -> str:
    """Kick off an image generation. Returns a prediction id (or stub sentinel).

    Never blocks waiting for the result.

    - `model_slug`: Replicate model (`owner/name` or `owner/name:version`);
      falls back to `settings.default_replicate_model`. Stub mode ignores it.
    - `image_input_paths`: source images for edit/compose/explore, sent as a
      list under `image_input_field` (models differ: `image_input`,
      `input_images`, …; see `ModelEntry.image_input_field`).
    - `seed`: only pass it for models that accept a `seed` input.
    """
    if settings.use_stub_generation:
        _generate_stub(task_id, generation_id, settings)
        return f"{_STUB_PREFIX}{generation_id}"

    if not settings.replicate_api_token:
        raise RuntimeError("Replicate API token is not configured.")
    chosen_model = model_slug or settings.default_replicate_model
    if not chosen_model:
        raise RuntimeError("No Replicate model is configured.")

    payload: dict[str, object] = {"prompt": prompt}
    if seed is not None:
        payload["seed"] = seed
    with ExitStack() as stack:
        if image_input_paths:
            payload[image_input_field] = [
                stack.enter_context(Path(p).open("rb")) for p in image_input_paths
            ]
        try:
            client = replicate.Client(api_token=settings.replicate_api_token)
            # `owner/name:version` pins a version; `owner/name` runs the latest.
            # Running by model name works for community and official models
            # alike and saves a "resolve latest version" API call.
            if ":" in chosen_model:
                version = chosen_model.split(":", 1)[1]
                prediction = client.predictions.create(version=version, input=payload)
            else:
                prediction = client.predictions.create(
                    model=chosen_model, input=payload
                )
        except Exception as e:
            raise RuntimeError(f"Failed to start generation: {e}") from e
    return str(prediction.id)


def poll_generation(
    prediction_id: str,
    task_id: str,
    generation_id: str,
    settings: AppSettings,
) -> GenerationResult:
    """Check the status of a running prediction.

    For stub predictions, returns completed immediately if the image is on disk
    (it should have been written synchronously by `start_generation`).
    """
    image_path = make_submission_image_path(
        settings.generated_dir, task_id, generation_id
    )

    if prediction_id.startswith(_STUB_PREFIX):
        if image_path.exists():
            return GenerationResult(status="completed", image_path=str(image_path))
        return GenerationResult(status="failed", error="Stub image is missing.")

    if not settings.replicate_api_token:
        return GenerationResult(
            status="failed", error="Replicate API token is not configured."
        )

    try:
        client = replicate.Client(api_token=settings.replicate_api_token)
        prediction = client.predictions.get(prediction_id)
    except Exception as e:
        return GenerationResult(
            status="failed", error=f"Could not poll prediction: {e}"
        )

    status = getattr(prediction, "status", None)
    if status in ("starting", "processing"):
        return GenerationResult(status="pending")
    if status == "succeeded":
        try:
            url = _extract_url(prediction.output)
        except Exception as e:
            return GenerationResult(
                status="failed", error=f"Could not read output URL: {e}"
            )
        try:
            download_image(url, image_path)
        except Exception as e:
            return GenerationResult(status="failed", error=str(e))
        return GenerationResult(status="completed", image_path=str(image_path))
    if status in ("failed", "canceled"):
        err = getattr(prediction, "error", None) or f"Prediction {status}."
        return GenerationResult(status="failed", error=str(err))
    return GenerationResult(
        status="failed", error=f"Unknown prediction status: {status!r}"
    )


def _generate_stub(task_id: str, generation_id: str, settings: AppSettings) -> Path:
    placeholder = settings.assets_dir / "placeholder" / "stub.png"
    dest = make_submission_image_path(settings.generated_dir, task_id, generation_id)
    shutil.copy(placeholder, dest)
    return dest


def _extract_url(output: object) -> str:
    if isinstance(output, str):
        return output
    if isinstance(output, list) and output:
        return _url_from_item(output[0])
    if hasattr(output, "url"):
        return _url_from_item(output)
    try:
        first = next(iter(output))  # type: ignore[call-overload]  # generator/iterator
    except TypeError, StopIteration:
        raise RuntimeError("Unexpected output from image generation service.") from None
    return _url_from_item(first)


def _url_from_item(item: object) -> str:
    if hasattr(item, "url"):
        return str(item.url)
    return str(item)
