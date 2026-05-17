"""Image generation via Replicate, structured for async resumability.

Two-step flow:

1. `start_generation` — non-blocking. Creates a Replicate prediction (or, in
   stub mode, writes the placeholder image synchronously). Returns a string
   identifier that is persisted on the submission.
2. `poll_generation` — checks whether the prediction has completed and, on
   success, downloads the image to disk. Called from the UI's reconciliation
   path on each rerun / fragment tick.

A stub prediction id has the form `stub:<submission_id>` so the poll path can
distinguish synchronous stub results from real Replicate predictions.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import replicate

from genai_cv_game.config import AppSettings
from genai_cv_game.storage import download_image, make_submission_image_path

_STUB_PREFIX = "stub:"


@dataclass
class GenerationResult:
    status: Literal["pending", "succeeded", "failed"]
    image_path: str | None = None
    error: str | None = None


def start_generation(
    prompt: str,
    round_id: str,
    submission_id: str,
    settings: AppSettings,
    model_slug: str | None = None,
) -> str:
    """Kick off an image generation. Returns a prediction id (or stub sentinel).

    Never blocks waiting for the result. Caller persists the returned id on the
    submission row and later passes it to `poll_generation`.

    `model_slug` selects which Replicate model to use. If omitted, falls back
    to `settings.default_replicate_model`. Stub mode ignores it.
    """
    if settings.use_stub_generation:
        _generate_stub(round_id, submission_id, settings)
        return f"{_STUB_PREFIX}{submission_id}"

    if not settings.replicate_api_token:
        raise RuntimeError("Replicate API token is not configured.")
    chosen_model = model_slug or settings.default_replicate_model
    if not chosen_model:
        raise RuntimeError("No Replicate model is configured.")

    try:
        client = replicate.Client(api_token=settings.replicate_api_token)
        version_id = _resolve_version(client, chosen_model)
        prediction = client.predictions.create(
            version=version_id, input={"prompt": prompt}
        )
    except Exception as e:
        raise RuntimeError(f"Failed to start generation: {e}") from e
    return str(prediction.id)


def poll_generation(
    prediction_id: str,
    round_id: str,
    submission_id: str,
    settings: AppSettings,
) -> GenerationResult:
    """Check the status of a running prediction.

    For stub predictions, returns succeeded immediately if the image is on disk
    (it should have been written synchronously by `start_generation`).
    """
    image_path = make_submission_image_path(
        settings.generated_dir, round_id, submission_id
    )

    if prediction_id.startswith(_STUB_PREFIX):
        if image_path.exists():
            return GenerationResult(status="succeeded", image_path=str(image_path))
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
        return GenerationResult(status="succeeded", image_path=str(image_path))
    if status in ("failed", "canceled"):
        err = getattr(prediction, "error", None) or f"Prediction {status}."
        return GenerationResult(status="failed", error=str(err))
    return GenerationResult(
        status="failed", error=f"Unknown prediction status: {status!r}"
    )


def _generate_stub(round_id: str, submission_id: str, settings: AppSettings) -> Path:
    placeholder = settings.assets_dir / "placeholder" / "stub.png"
    dest = make_submission_image_path(settings.generated_dir, round_id, submission_id)
    shutil.copy(placeholder, dest)
    return dest


def _resolve_version(client: replicate.Client, model: str) -> str:
    """Return the latest version id for an `owner/name` model reference.

    If the model string already looks like `owner/name:version`, the explicit
    version is used verbatim and no API call is made.
    """
    if ":" in model:
        return model.split(":", 1)[1]
    try:
        m = client.models.get(model)
        return str(m.latest_version.id)
    except Exception as e:
        raise RuntimeError(f"Could not resolve model {model!r}: {e}") from e


def _extract_url(output: object) -> str:
    if isinstance(output, str):
        return output
    if isinstance(output, list) and output:
        return _url_from_item(output[0])
    if hasattr(output, "url"):
        return _url_from_item(output)
    try:
        first = next(iter(output))  # generator/iterator
    except (TypeError, StopIteration):
        raise RuntimeError("Unexpected output from image generation service.")
    return _url_from_item(first)


def _url_from_item(item: object) -> str:
    if hasattr(item, "url"):
        return str(item.url)
    return str(item)
