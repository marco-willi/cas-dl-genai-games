"""JSON-backed catalog of selectable Replicate models.

The catalog file is a JSON list:

    [
      {
        "id": "flux-schnell",
        "slug": "black-forest-labs/flux-schnell",
        "display_name": "FLUX Schnell",
        "description": "Fast, lightweight; good for iteration.",
        "is_enabled": true
      },
      ...
    ]

`slug` is the Replicate model identifier passed to the API. `id` is a stable
short key; `display_name` is what students see. To disable a model for class,
set `is_enabled: false` in the JSON and restart the app.
"""

from __future__ import annotations

import json
from pathlib import Path

from genai_cv_game.models import ModelEntry


def load_models(models_path: Path) -> list[ModelEntry]:
    """Read and validate the model catalog from JSON.

    Returns an empty list if the file does not exist. Entries are sorted by
    `sort_order` then `display_name` so the student dropdown is stable.
    """
    if not models_path.exists():
        return []

    raw = json.loads(models_path.read_text())
    if not isinstance(raw, list):
        raise ValueError(f"Models file must contain a JSON list: {models_path}")

    entries: list[ModelEntry] = []
    seen_ids: set[str] = set()
    seen_slugs: set[str] = set()
    for i, item in enumerate(raw):
        for field in ("id", "slug", "display_name"):
            if field not in item or not item[field]:
                raise ValueError(
                    f"Model entry missing required field '{field}': {item}"
                )
        if item["id"] in seen_ids:
            raise ValueError(f"Duplicate model id: '{item['id']}'")
        if item["slug"] in seen_slugs:
            raise ValueError(f"Duplicate model slug: '{item['slug']}'")
        seen_ids.add(item["id"])
        seen_slugs.add(item["slug"])
        entries.append(
            ModelEntry(
                id=item["id"],
                slug=item["slug"],
                display_name=item["display_name"],
                description=item.get("description"),
                is_enabled=bool(item.get("is_enabled", True)),
                sort_order=int(item.get("sort_order", i)),
            )
        )

    return sorted(entries, key=lambda m: (m.sort_order, m.display_name))


def load_enabled_models(models_path: Path) -> list[ModelEntry]:
    return [m for m in load_models(models_path) if m.is_enabled]


def find_model(models_path: Path, slug: str) -> ModelEntry | None:
    for m in load_models(models_path):
        if m.slug == slug:
            return m
    return None
