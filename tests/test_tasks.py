import json

import pytest

from genai_cv_game.db import (
    get_all_tasks,
    get_available_tasks,
    init_db,
    set_task_availability,
)
from genai_cv_game.tasks import load_task_definitions, sync_tasks_from_json


def _write_tasks(tmp_path, tasks: list[dict]) -> object:
    p = tmp_path / "tasks.json"
    p.write_text(json.dumps(tasks))
    return p


_VALID = [
    {
        "id": "b1",
        "title": "Business 1",
        "description": "desc",
        "mode": "business",
        "target_image_path": None,
    },
    {
        "id": "m1",
        "title": "Match 1",
        "description": "desc",
        "mode": "match",
        "target_image_path": "assets/img.jpg",
    },
]


def test_load_valid_tasks(tmp_path):
    p = _write_tasks(tmp_path, _VALID)
    tasks = load_task_definitions(p)
    assert len(tasks) == 2
    assert tasks[0].id == "b1"
    assert tasks[0].mode == "business"
    assert tasks[1].id == "m1"
    assert tasks[1].target_image_path == "assets/img.jpg"


def test_load_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_task_definitions(tmp_path / "nonexistent.json")


def test_load_missing_required_field(tmp_path):
    p = _write_tasks(
        tmp_path, [{"id": "t1", "title": "T", "description": "d"}]
    )  # no mode
    with pytest.raises(ValueError, match="mode"):
        load_task_definitions(p)


def test_load_invalid_mode(tmp_path):
    p = _write_tasks(
        tmp_path, [{"id": "t1", "title": "T", "description": "d", "mode": "unknown"}]
    )
    with pytest.raises(ValueError, match="Invalid mode"):
        load_task_definitions(p)


def test_load_duplicate_ids(tmp_path):
    p = _write_tasks(
        tmp_path,
        [
            {"id": "t1", "title": "T", "description": "d", "mode": "business"},
            {"id": "t1", "title": "T2", "description": "d", "mode": "match"},
        ],
    )
    with pytest.raises(ValueError, match="Duplicate"):
        load_task_definitions(p)


def test_sync_upserts_tasks(tmp_path):
    p = _write_tasks(tmp_path, _VALID)
    db = tmp_path / "app.db"
    sync_tasks_from_json(p, db)
    tasks = get_all_tasks(db)
    assert {t.id for t in tasks} == {"b1", "m1"}


def test_sync_makes_tasks_available(tmp_path):
    p = _write_tasks(tmp_path, _VALID)
    db = tmp_path / "app.db"
    sync_tasks_from_json(p, db)
    available = get_available_tasks(db)
    assert {t.id for t in available} == {"b1", "m1"}


def test_sync_preserves_availability(tmp_path):
    p = _write_tasks(tmp_path, _VALID)
    db = tmp_path / "app.db"
    init_db(db)
    sync_tasks_from_json(p, db)
    set_task_availability(db, "m1", False)

    # re-sync should not re-enable a task the admin disabled
    sync_tasks_from_json(p, db)
    assert {t.id for t in get_available_tasks(db)} == {"b1"}


def test_sync_creates_tables(tmp_path):
    p = _write_tasks(tmp_path, _VALID)
    db = tmp_path / "fresh.db"
    assert not db.exists()
    sync_tasks_from_json(p, db)
    assert db.exists()
    assert len(get_all_tasks(db)) == 2


# ── edit / compose modes ────────────────────────────────────────────────────


def _make_input(tmp_path, name: str) -> str:
    p = tmp_path / name
    p.write_bytes(b"\x89PNG fake")
    return str(p)


def test_load_edit_task_with_one_input(tmp_path):
    img = _make_input(tmp_path, "src.jpg")
    p = _write_tasks(
        tmp_path,
        [
            {
                "id": "edit1",
                "title": "Edit",
                "description": "d",
                "mode": "edit",
                "input_image_paths": [img],
            }
        ],
    )
    [t] = load_task_definitions(p)
    assert t.mode == "edit"
    assert t.input_image_paths == [img]


def test_load_edit_task_requires_exactly_one_input(tmp_path):
    img1 = _make_input(tmp_path, "a.jpg")
    img2 = _make_input(tmp_path, "b.jpg")
    p = _write_tasks(
        tmp_path,
        [
            {
                "id": "edit1",
                "title": "Edit",
                "description": "d",
                "mode": "edit",
                "input_image_paths": [img1, img2],
            }
        ],
    )
    with pytest.raises(ValueError, match="exactly one"):
        load_task_definitions(p)


def test_load_edit_task_rejects_missing_file(tmp_path):
    p = _write_tasks(
        tmp_path,
        [
            {
                "id": "edit1",
                "title": "Edit",
                "description": "d",
                "mode": "edit",
                "input_image_paths": [str(tmp_path / "nope.jpg")],
            }
        ],
    )
    with pytest.raises(ValueError, match="not found"):
        load_task_definitions(p)


def test_load_compose_task_requires_at_least_one_input(tmp_path):
    p = _write_tasks(
        tmp_path,
        [
            {
                "id": "compose1",
                "title": "Compose",
                "description": "d",
                "mode": "compose",
                "input_image_paths": [],
            }
        ],
    )
    with pytest.raises(ValueError, match="at least one"):
        load_task_definitions(p)


def test_load_comparison_task(tmp_path):
    p = _write_tasks(
        tmp_path,
        [
            {
                "id": "cmp1",
                "title": "Comparison",
                "description": "d",
                "mode": "comparison",
            }
        ],
    )
    [t] = load_task_definitions(p)
    assert t.mode == "comparison"
    assert t.input_image_paths == []
    assert t.vote_images == []


def test_load_explore_task_needs_no_input_images(tmp_path):
    p = _write_tasks(
        tmp_path,
        [
            {
                "id": "explore1",
                "title": "Explore",
                "description": "d",
                "mode": "explore",
            }
        ],
    )
    [t] = load_task_definitions(p)
    assert t.mode == "explore"
    assert t.input_image_paths == []


def test_load_compose_task_allows_multiple_inputs(tmp_path):
    img1 = _make_input(tmp_path, "cut.png")
    img2 = _make_input(tmp_path, "ref.png")
    p = _write_tasks(
        tmp_path,
        [
            {
                "id": "compose1",
                "title": "Compose",
                "description": "d",
                "mode": "compose",
                "input_image_paths": [img1, img2],
            }
        ],
    )
    [t] = load_task_definitions(p)
    assert t.input_image_paths == [img1, img2]


# ── vote mode ────────────────────────────────────────────────────────────────


def _vote_entry(tmp_path, img_id: str, label: str) -> dict:
    return {
        "id": img_id,
        "path": _make_input(tmp_path, f"{img_id}.png"),
        "label": label,
    }


def test_load_vote_task(tmp_path):
    images = [
        _vote_entry(tmp_path, "i1", "real"),
        _vote_entry(tmp_path, "i2", "synthetic"),
    ]
    p = _write_tasks(
        tmp_path,
        [
            {
                "id": "vote1",
                "title": "Vote",
                "description": "d",
                "mode": "vote",
                "vote_images": images,
            }
        ],
    )
    [t] = load_task_definitions(p)
    assert t.mode == "vote"
    assert [vi.id for vi in t.vote_images] == ["i1", "i2"]
    assert t.vote_images[0].label == "real"
    assert t.vote_images[0].sort_order == 0


def test_vote_task_requires_images(tmp_path):
    p = _write_tasks(
        tmp_path,
        [
            {
                "id": "vote1",
                "title": "Vote",
                "description": "d",
                "mode": "vote",
                "vote_images": [],
            }
        ],
    )
    with pytest.raises(ValueError, match="non-empty 'vote_images'"):
        load_task_definitions(p)


def test_vote_task_rejects_bad_label(tmp_path):
    p = _write_tasks(
        tmp_path,
        [
            {
                "id": "vote1",
                "title": "Vote",
                "description": "d",
                "mode": "vote",
                "vote_images": [_vote_entry(tmp_path, "i1", "fake")],
            }
        ],
    )
    with pytest.raises(ValueError, match="invalid label"):
        load_task_definitions(p)


def test_vote_task_rejects_duplicate_image_id(tmp_path):
    p = _write_tasks(
        tmp_path,
        [
            {
                "id": "vote1",
                "title": "Vote",
                "description": "d",
                "mode": "vote",
                "vote_images": [
                    _vote_entry(tmp_path, "i1", "real"),
                    {
                        "id": "i1",
                        "path": _make_input(tmp_path, "dup.png"),
                        "label": "synthetic",
                    },
                ],
            }
        ],
    )
    with pytest.raises(ValueError, match="duplicate vote image"):
        load_task_definitions(p)


def test_vote_task_rejects_missing_file(tmp_path):
    p = _write_tasks(
        tmp_path,
        [
            {
                "id": "vote1",
                "title": "Vote",
                "description": "d",
                "mode": "vote",
                "vote_images": [
                    {"id": "i1", "path": str(tmp_path / "nope.png"), "label": "real"}
                ],
            }
        ],
    )
    with pytest.raises(ValueError, match="not found"):
        load_task_definitions(p)


def test_non_vote_task_rejects_vote_images(tmp_path):
    p = _write_tasks(
        tmp_path,
        [
            {
                "id": "b1",
                "title": "Business",
                "description": "d",
                "mode": "business",
                "vote_images": [_vote_entry(tmp_path, "i1", "real")],
            }
        ],
    )
    with pytest.raises(ValueError, match="only valid for mode 'vote'"):
        load_task_definitions(p)


def test_sync_populates_vote_images(tmp_path):
    from genai_cv_game.db import get_vote_images

    images = [
        _vote_entry(tmp_path, "i1", "real"),
        _vote_entry(tmp_path, "i2", "synthetic"),
    ]
    p = _write_tasks(
        tmp_path,
        [
            {
                "id": "vote1",
                "title": "Vote",
                "description": "d",
                "mode": "vote",
                "vote_images": images,
            }
        ],
    )
    db = tmp_path / "app.db"
    sync_tasks_from_json(p, db)
    rows = get_vote_images(db, "vote1")
    assert [r.id for r in rows] == ["i1", "i2"]
    assert rows[1].label == "synthetic"
