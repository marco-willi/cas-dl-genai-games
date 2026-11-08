"""JSON-backed catalog of selectable Replicate models (`data/models.json`).

The catalog file is a JSON list of `ModelEntry` objects:

    [
      {
        "id": "flux-2-flex",
        "slug": "black-forest-labs/flux-2-flex",
        "display_name": "FLUX 2 Flex",
        "description": "...",
        "supports_image_input": true,
        "image_input_field": "input_images",
        "supports_seed": true,
        "is_enabled": true
      },
      ...
    ]

`slug` is the Replicate model identifier passed to the API. To disable a model
for class, set `is_enabled: false` and save — the file is re-read within a few
seconds (cached per modification time).
"""

from __future__ import annotations

import json
import time
from functools import lru_cache
from pathlib import Path

from pydantic import TypeAdapter

from genai_cv_game.models import ModelEntry

_MODEL_LIST = TypeAdapter(list[ModelEntry])

# Each page render looks models up many times (one per image card), and file
# system calls can be slow (~1 ms on some mounts). So the file's mtime is
# re-checked at most every few seconds; edits still show up without a restart.
_RECHECK_SECONDS = 5.0
_recent: dict[Path, tuple[float, tuple[ModelEntry, ...]]] = {}


def load_models(models_path: Path) -> list[ModelEntry]:
    """Read and validate the model catalog (cached until the file changes).

    Returns an empty list if the file does not exist. Entries are sorted by
    `sort_order` (default: position in the file) then `display_name`.
    """
    now = time.monotonic()
    hit = _recent.get(models_path)
    if hit is not None and now - hit[0] < _RECHECK_SECONDS:
        return list(hit[1])
    try:
        mtime = models_path.stat().st_mtime_ns
    except FileNotFoundError:
        models: tuple[ModelEntry, ...] = ()
    else:
        models = _load_models_cached(models_path, mtime)
    _recent[models_path] = (now, models)
    return list(models)


@lru_cache(maxsize=8)
def _load_models_cached(models_path: Path, _mtime_ns: int) -> tuple[ModelEntry, ...]:
    raw = json.loads(models_path.read_text())
    if not isinstance(raw, list):
        raise ValueError(f"Models file must contain a JSON list: {models_path}")
    for i, item in enumerate(raw):
        if isinstance(item, dict):
            item.setdefault("sort_order", i)
    entries = _MODEL_LIST.validate_python(raw)

    seen_ids: set[str] = set()
    seen_slugs: set[str] = set()
    for m in entries:
        if not (m.id and m.slug and m.display_name):
            missing = [f for f in ("id", "slug", "display_name") if not getattr(m, f)]
            raise ValueError(f"Model entry missing required field '{missing[0]}': {m}")
        if m.id in seen_ids:
            raise ValueError(f"Duplicate model id: '{m.id}'")
        if m.slug in seen_slugs:
            raise ValueError(f"Duplicate model slug: '{m.slug}'")
        seen_ids.add(m.id)
        seen_slugs.add(m.slug)
    return tuple(sorted(entries, key=lambda m: (m.sort_order, m.display_name)))


def load_enabled_models(models_path: Path) -> list[ModelEntry]:
    return [m for m in load_models(models_path) if m.is_enabled]


def find_model(models_path: Path, slug: str | None) -> ModelEntry | None:
    if not slug:
        return None
    return next((m for m in load_models(models_path) if m.slug == slug), None)


def display_name(models_path: Path, slug: str) -> str:
    """Catalog display name for a slug, or the slug itself if unknown."""
    model = find_model(models_path, slug)
    return model.display_name if model else slug
