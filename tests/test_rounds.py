import json

import pytest

from genai_cv_game.db import get_active_round, init_db, set_active_round
from genai_cv_game.rounds import load_round_definitions, sync_rounds_from_json


def _write_rounds(tmp_path, rounds: list[dict]) -> object:
    p = tmp_path / "rounds.json"
    p.write_text(json.dumps(rounds))
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


def test_load_valid_rounds(tmp_path):
    p = _write_rounds(tmp_path, _VALID)
    rounds = load_round_definitions(p)
    assert len(rounds) == 2
    assert rounds[0].id == "b1"
    assert rounds[0].mode == "business"
    assert rounds[1].id == "m1"
    assert rounds[1].target_image_path == "assets/img.jpg"


def test_load_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_round_definitions(tmp_path / "nonexistent.json")


def test_load_missing_required_field(tmp_path):
    p = _write_rounds(
        tmp_path, [{"id": "r1", "title": "T", "description": "d"}]
    )  # no mode
    with pytest.raises(ValueError, match="mode"):
        load_round_definitions(p)


def test_load_invalid_mode(tmp_path):
    p = _write_rounds(
        tmp_path, [{"id": "r1", "title": "T", "description": "d", "mode": "unknown"}]
    )
    with pytest.raises(ValueError, match="Invalid mode"):
        load_round_definitions(p)


def test_load_duplicate_ids(tmp_path):
    p = _write_rounds(
        tmp_path,
        [
            {"id": "r1", "title": "T", "description": "d", "mode": "business"},
            {"id": "r1", "title": "T2", "description": "d", "mode": "match"},
        ],
    )
    with pytest.raises(ValueError, match="Duplicate"):
        load_round_definitions(p)


def test_sync_upserts_rounds(tmp_path):
    p = _write_rounds(tmp_path, _VALID)
    db = tmp_path / "app.db"
    sync_rounds_from_json(p, db)
    from genai_cv_game.db import get_all_rounds

    rounds = get_all_rounds(db)
    assert {r.id for r in rounds} == {"b1", "m1"}


def test_sync_activates_first_round(tmp_path):
    p = _write_rounds(tmp_path, _VALID)
    db = tmp_path / "app.db"
    sync_rounds_from_json(p, db)
    active = get_active_round(db)
    assert active is not None
    assert active.id == "b1"


def test_sync_preserves_existing_active(tmp_path):
    p = _write_rounds(tmp_path, _VALID)
    db = tmp_path / "app.db"
    init_db(db)
    sync_rounds_from_json(p, db)
    set_active_round(db, "m1")

    # re-sync should not change the active round
    sync_rounds_from_json(p, db)
    assert get_active_round(db).id == "m1"


def test_sync_creates_tables(tmp_path):
    p = _write_rounds(tmp_path, _VALID)
    db = tmp_path / "fresh.db"
    assert not db.exists()
    sync_rounds_from_json(p, db)
    assert db.exists()
    assert get_active_round(db) is not None


# ── edit / compose modes ────────────────────────────────────────────────────


def _make_input(tmp_path, name: str) -> str:
    p = tmp_path / name
    p.write_bytes(b"\x89PNG fake")
    return str(p)


def test_load_edit_round_with_one_input(tmp_path):
    img = _make_input(tmp_path, "src.jpg")
    p = _write_rounds(
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
    [r] = load_round_definitions(p)
    assert r.mode == "edit"
    assert r.input_image_paths == [img]


def test_load_edit_round_requires_exactly_one_input(tmp_path):
    img1 = _make_input(tmp_path, "a.jpg")
    img2 = _make_input(tmp_path, "b.jpg")
    p = _write_rounds(
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
        load_round_definitions(p)


def test_load_edit_round_rejects_missing_file(tmp_path):
    p = _write_rounds(
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
        load_round_definitions(p)


def test_load_compose_round_requires_at_least_one_input(tmp_path):
    p = _write_rounds(
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
        load_round_definitions(p)


def test_load_compose_round_allows_multiple_inputs(tmp_path):
    img1 = _make_input(tmp_path, "cut.png")
    img2 = _make_input(tmp_path, "ref.png")
    p = _write_rounds(
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
    [r] = load_round_definitions(p)
    assert r.input_image_paths == [img1, img2]
