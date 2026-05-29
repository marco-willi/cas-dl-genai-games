from __future__ import annotations

import json
from pathlib import Path

from genai_cv_game.db import init_db, insert_or_update_task, sync_vote_images
from genai_cv_game.models import VOTE_LABELS, Task, VoteImage

_VALID_MODES = frozenset(
    {"business", "match", "edit", "compose", "explore", "vote", "comparison"}
)
_IMAGE_INPUT_MODES = frozenset({"edit", "compose"})


def load_task_definitions(tasks_path: Path) -> list[Task]:
    if not tasks_path.exists():
        raise FileNotFoundError(f"Tasks file not found: {tasks_path}")

    items = json.loads(tasks_path.read_text())

    tasks = []
    seen_ids: set[str] = set()
    for item in items:
        for field in ("id", "title", "description", "mode"):
            if field not in item or not item[field]:
                raise ValueError(f"Task entry missing required field '{field}': {item}")
        if item["mode"] not in _VALID_MODES:
            raise ValueError(
                f"Invalid mode '{item['mode']}' for task '{item['id']}'. "
                f"Must be one of: {sorted(_VALID_MODES)}"
            )
        if item["id"] in seen_ids:
            raise ValueError(f"Duplicate task id: '{item['id']}'")
        seen_ids.add(item["id"])

        input_image_paths = item.get("input_image_paths") or []
        if not isinstance(input_image_paths, list) or not all(
            isinstance(p, str) for p in input_image_paths
        ):
            raise ValueError(
                f"Task '{item['id']}': 'input_image_paths' must be a list of strings."
            )

        if item["mode"] == "edit" and len(input_image_paths) != 1:
            raise ValueError(
                f"Task '{item['id']}' (edit) must declare exactly one "
                f"input_image_paths entry."
            )
        if item["mode"] == "compose" and len(input_image_paths) < 1:
            raise ValueError(
                f"Task '{item['id']}' (compose) must declare at least one "
                f"input_image_paths entry."
            )
        for p in input_image_paths:
            if not Path(p).exists():
                raise ValueError(
                    f"Task '{item['id']}': input image not found on disk: {p}"
                )

        vote_images = _parse_vote_images(item)

        tasks.append(
            Task(
                id=item["id"],
                title=item["title"],
                description=item["description"],
                mode=item["mode"],
                target_image_path=item.get("target_image_path"),
                input_image_paths=input_image_paths,
                vote_images=vote_images,
            )
        )

    return tasks


def _parse_vote_images(item: dict) -> list[VoteImage]:
    """Validate and build the VoteImage list for a task entry.

    Only `vote`-mode tasks may declare `vote_images`; the field is required and
    non-empty for them. Each entry needs a unique `id`, an existing `path`, and
    a label in {real, synthetic}.
    """
    raw = item.get("vote_images")
    if item["mode"] != "vote":
        if raw:
            raise ValueError(
                f"Task '{item['id']}': 'vote_images' is only valid for mode 'vote'."
            )
        return []

    if not isinstance(raw, list) or not raw:
        raise ValueError(
            f"Task '{item['id']}' (vote) must declare a non-empty 'vote_images' list."
        )

    images: list[VoteImage] = []
    seen: set[str] = set()
    for order, entry in enumerate(raw):
        for field in ("id", "path", "label"):
            if field not in entry or entry[field] in (None, ""):
                raise ValueError(
                    f"Task '{item['id']}': vote image missing field '{field}': {entry}"
                )
        if entry["label"] not in VOTE_LABELS:
            raise ValueError(
                f"Task '{item['id']}': vote image '{entry['id']}' has invalid label "
                f"'{entry['label']}'. Must be one of: {sorted(VOTE_LABELS)}"
            )
        if entry["id"] in seen:
            raise ValueError(
                f"Task '{item['id']}': duplicate vote image id '{entry['id']}'."
            )
        seen.add(entry["id"])
        if not Path(entry["path"]).exists():
            raise ValueError(
                f"Task '{item['id']}': vote image not found on disk: {entry['path']}"
            )
        images.append(
            VoteImage(
                id=entry["id"],
                image_path=entry["path"],
                label=entry["label"],
                sort_order=order,
            )
        )
    return images


def sync_tasks_from_json(tasks_path: Path, db_path: Path) -> None:
    tasks = load_task_definitions(tasks_path)
    init_db(db_path)
    for task in tasks:
        insert_or_update_task(db_path, task)
        if task.mode == "vote":
            sync_vote_images(db_path, task.id, task.vote_images)
