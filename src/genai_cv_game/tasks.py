"""Load and validate `data/tasks.json`, then sync it into the database."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    TypeAdapter,
    field_validator,
    model_validator,
)

from genai_cv_game.db import init_db, insert_or_update_task, sync_vote_images
from genai_cv_game.models import (
    ALL_MODES,
    VOTE_LABELS,
    Mode,
    Task,
    VoteImage,
    normalize_mode,
)

NonEmptyStr = Annotated[str, StringConstraints(min_length=1)]


class VoteImageDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: NonEmptyStr
    path: NonEmptyStr
    label: str
    hint: str = ""
    pair: str = ""

    @field_validator("label")
    @classmethod
    def _check_label(cls, v: str) -> str:
        if v not in VOTE_LABELS:
            raise ValueError(
                f"invalid label '{v}'. Must be one of: {sorted(VOTE_LABELS)}"
            )
        return v


class TaskDefinition(BaseModel):
    """One entry of tasks.json, with the per-mode rules enforced."""

    model_config = ConfigDict(extra="forbid")

    id: NonEmptyStr
    title: NonEmptyStr
    description: NonEmptyStr
    mode: Mode
    nav_title: str | None = None
    section: str | None = None
    icon: str | None = None
    target_image_path: str | None = None
    input_image_paths: list[str] = []
    gallery_picks: int = Field(default=1, ge=1, le=4)
    vote_images: list[VoteImageDefinition] = []

    @field_validator("mode", mode="before")
    @classmethod
    def _check_mode(cls, v: object) -> object:
        v = normalize_mode(v)
        if isinstance(v, str) and v and v not in ALL_MODES:
            raise ValueError(f"Invalid mode '{v}'. Must be one of: {sorted(ALL_MODES)}")
        return v

    @field_validator("input_image_paths", "vote_images", mode="before")
    @classmethod
    def _none_is_empty(cls, v: object) -> object:
        return [] if v is None else v

    @model_validator(mode="after")
    def _check_mode_rules(self) -> TaskDefinition:
        n_inputs = len(self.input_image_paths)
        if self.mode == "edit" and n_inputs != 1:
            raise ValueError(
                "edit tasks must declare exactly one input_image_paths entry."
            )
        if self.mode == "compose" and n_inputs < 1:
            raise ValueError(
                "compose tasks must declare at least one input_image_paths entry."
            )
        for p in self.input_image_paths:
            if not Path(p).exists():
                raise ValueError(f"input image not found on disk: {p}")

        if self.mode != "vote":
            if self.vote_images:
                raise ValueError("'vote_images' is only valid for mode 'vote'.")
            return self
        if not self.vote_images:
            raise ValueError("vote tasks must declare a non-empty 'vote_images' list.")
        seen: set[str] = set()
        for img in self.vote_images:
            if img.id in seen:
                raise ValueError(f"duplicate vote image id '{img.id}'.")
            seen.add(img.id)
            if not Path(img.path).exists():
                raise ValueError(f"vote image not found on disk: {img.path}")
        self._check_pairs()
        return self

    def _check_pairs(self) -> None:
        """A pair is exactly one real and one synthetic image, listed adjacently."""
        labels: dict[str, list[str]] = {}
        for img in self.vote_images:
            if img.pair:
                labels.setdefault(img.pair, []).append(img.label)
        for pair, pair_labels in labels.items():
            if sorted(pair_labels) != ["real", "synthetic"]:
                raise ValueError(
                    f"vote pair '{pair}' must have exactly one 'real' and one "
                    f"'synthetic' image, got {pair_labels}."
                )
        order = [img.pair for img in self.vote_images if img.pair]
        for i in range(0, len(order), 2):
            if order[i] != order[i + 1]:
                raise ValueError(
                    f"the two images of vote pair '{order[i]}' must be listed next "
                    "to each other."
                )

    def to_task(self, sort_order: int) -> Task:
        return Task(
            **self.model_dump(exclude={"vote_images"}),
            vote_images=[
                VoteImage(
                    id=img.id,
                    image_path=img.path,
                    label=img.label,  # type: ignore[arg-type]
                    hint=img.hint,
                    pair=img.pair,
                    sort_order=i,
                )
                for i, img in enumerate(self.vote_images)
            ],
            sort_order=sort_order,
        )


_TASK_LIST = TypeAdapter(list[TaskDefinition])


def load_task_definitions(tasks_path: Path) -> list[Task]:
    """Parse and validate tasks.json. Raises ValueError with the offending task."""
    if not tasks_path.exists():
        raise FileNotFoundError(f"Tasks file not found: {tasks_path}")

    definitions = _TASK_LIST.validate_json(tasks_path.read_text())

    seen: set[str] = set()
    for d in definitions:
        if d.id in seen:
            raise ValueError(f"Duplicate task id: '{d.id}'")
        seen.add(d.id)
    return [d.to_task(sort_order=i) for i, d in enumerate(definitions)]


def sync_tasks_from_json(tasks_path: Path, db_path: Path) -> None:
    tasks = load_task_definitions(tasks_path)
    init_db(db_path)
    for task in tasks:
        insert_or_update_task(db_path, task)
        if task.mode == "vote":
            sync_vote_images(db_path, task.id, task.vote_images)
