from __future__ import annotations

import json
from pathlib import Path

from genai_cv_game.db import (
    get_active_round,
    init_db,
    insert_or_update_round,
    set_active_round,
)
from genai_cv_game.models import Round

_VALID_MODES = frozenset({"business", "match"})


def load_round_definitions(rounds_path: Path) -> list[Round]:
    if not rounds_path.exists():
        raise FileNotFoundError(f"Rounds file not found: {rounds_path}")

    items = json.loads(rounds_path.read_text())

    rounds = []
    seen_ids: set[str] = set()
    for item in items:
        for field in ("id", "title", "description", "mode"):
            if field not in item or not item[field]:
                raise ValueError(
                    f"Round entry missing required field '{field}': {item}"
                )
        if item["mode"] not in _VALID_MODES:
            raise ValueError(
                f"Invalid mode '{item['mode']}' for round '{item['id']}'. "
                f"Must be one of: {sorted(_VALID_MODES)}"
            )
        if item["id"] in seen_ids:
            raise ValueError(f"Duplicate round id: '{item['id']}'")
        seen_ids.add(item["id"])
        rounds.append(
            Round(
                id=item["id"],
                title=item["title"],
                description=item["description"],
                mode=item["mode"],
                target_image_path=item.get("target_image_path"),
            )
        )

    return rounds


def sync_rounds_from_json(rounds_path: Path, db_path: Path) -> None:
    rounds = load_round_definitions(rounds_path)
    init_db(db_path)
    for round in rounds:
        insert_or_update_round(db_path, round)
    if get_active_round(db_path) is None:
        set_active_round(db_path, rounds[0].id)
