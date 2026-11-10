"""Pydantic data models and the task-mode vocabulary.

Every model here can be built straight from a `sqlite3.Row` via
`Model.model_validate(dict(row))`: SQLite stores booleans as 0/1 (coerced by
pydantic) and lists as JSON text (parsed by the `_parse_json_list` validators).
"""

from __future__ import annotations

import json
from typing import Literal

from pydantic import BaseModel, field_validator

# ── Task modes ───────────────────────────────────────────────────────────────

Mode = Literal["text2img", "match", "edit", "compose", "explore", "vote", "comparison"]
ALL_MODES: frozenset[str] = frozenset(Mode.__args__)  # type: ignore[attr-defined]
# Old names still accepted in tasks.json / the DB, mapped on load.
MODE_ALIASES: dict[str, str] = {"business": "text2img"}

# Modes whose source image(s) are fixed by the task definition.
FIXED_INPUT_MODES: frozenset[str] = frozenset({"edit", "compose"})
# Modes where the student uploads their own source image.
UPLOAD_INPUT_MODES: frozenset[str] = frozenset({"explore"})
# Modes that send a source image to the model (need `supports_image_input`).
IMAGE_INPUT_MODES: frozenset[str] = FIXED_INPUT_MODES | UPLOAD_INPUT_MODES
# Modes without any image generation.
NON_GENERATING_MODES: frozenset[str] = frozenset({"vote"})

GenerationStatus = Literal["pending", "completed", "failed"]
GENERATION_STATUSES: frozenset[str] = frozenset(GenerationStatus.__args__)  # type: ignore[attr-defined]

VoteLabel = Literal["real", "synthetic"]
VOTE_LABELS: frozenset[str] = frozenset(VoteLabel.__args__)  # type: ignore[attr-defined]


def normalize_mode(value: object) -> object:
    return MODE_ALIASES.get(value, value) if isinstance(value, str) else value


def _parse_json_list(value: object) -> object:
    if isinstance(value, str):
        return json.loads(value or "[]")
    return [] if value is None else value


def _parse_json_dict(value: object) -> object:
    if isinstance(value, str):
        return json.loads(value or "{}")
    return {} if value is None else value


# ── Models ───────────────────────────────────────────────────────────────────


class VoteImage(BaseModel):
    """One pre-labelled image shown in a `vote`-mode task.

    The `label` (and optional `hint` explaining the tell-tale signs) is revealed
    only once the admin opens the results.
    """

    id: str
    task_id: str = ""
    image_path: str
    label: VoteLabel
    hint: str = ""
    # Images sharing a pair id show the same scene (one real, one AI) and are
    # displayed side by side; "" means unpaired.
    pair: str = ""
    sort_order: int = 0
    created_at: str = ""
    updated_at: str = ""


class Task(BaseModel):
    id: str
    title: str
    description: str
    mode: Mode
    # Short label for the sidebar, a navigation section, and a Material icon.
    nav_title: str | None = None
    section: str | None = None
    icon: str | None = None
    target_image_path: str | None = None
    input_image_paths: list[str] = []
    vote_images: list[VoteImage] = []
    # Friendly names for `input_image_paths` in the source picker (path -> label).
    input_image_labels: dict[str, str] = {}
    # explore tasks: also offer "no source image, text to image" in the picker.
    allow_text_only: bool = False
    # How many results each student may share in the gallery (shown side by side).
    gallery_picks: int = 1
    is_available: bool = True
    sort_order: int = 0
    created_at: str = ""
    updated_at: str = ""

    _mode = field_validator("mode", mode="before")(normalize_mode)
    _inputs = field_validator("input_image_paths", mode="before")(_parse_json_list)
    _labels = field_validator("input_image_labels", mode="before")(_parse_json_dict)

    @property
    def short_title(self) -> str:
        return self.nav_title or self.title

    @property
    def generates_images(self) -> bool:
        return self.mode not in NON_GENERATING_MODES


class Generation(BaseModel):
    """One generation attempt by a user on a task.

    A user may accumulate up to `AppSettings.generation_budget` non-failed rows
    per task; at most one of them has `in_gallery=True` when the user promotes
    a favourite into the task's public gallery. `hidden=True` means the admin
    pulled it from the gallery; it can no longer be shared. Rows created by one
    comparison round share a `batch_id`.
    """

    id: str
    task_id: str
    user_name: str
    prompt: str
    image_path: str | None = None
    status: GenerationStatus
    error_message: str | None = None
    prediction_id: str | None = None
    model_slug: str | None = None
    seed: int | None = None
    batch_id: str | None = None
    # Source image the model edited (prepared asset or saved upload), if any.
    input_image_path: str | None = None
    in_gallery: bool = False
    hidden: bool = False
    created_at: str
    updated_at: str


class ModelEntry(BaseModel):
    """An entry in the catalog of selectable Replicate models (`models.json`).

    `image_input_field` is the model's input name for source images — Replicate
    models differ (`image_input` vs `input_images`). `supports_seed` marks
    models that accept an integer `seed` input.
    """

    id: str
    slug: str
    display_name: str
    description: str | None = None
    is_enabled: bool = True
    supports_image_input: bool = False
    image_input_field: str = "image_input"
    supports_seed: bool = False
    sort_order: int = 0
