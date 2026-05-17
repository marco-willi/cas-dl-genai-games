"""Tests for the JSON-only model catalog and submission threading of model_slug."""

import json
from pathlib import Path

import pytest

from genai_cv_game.db import (
    choose_submission,
    create_submission,
    get_submissions_for_round,
    get_team_submissions,
    init_db,
    insert_or_update_round,
    update_submission_status,
)
from genai_cv_game.model_catalog import (
    find_model,
    load_enabled_models,
    load_models,
)
from genai_cv_game.models import Round


def _write_models(tmp_path: Path, items: list[dict]) -> Path:
    p = tmp_path / "models.json"
    p.write_text(json.dumps(items))
    return p


def _round() -> Round:
    return Round(id="r1", title="T", description="d", mode="business")


# ── JSON loader ─────────────────────────────────────────────────────────────


def test_load_missing_file_returns_empty(tmp_path):
    assert load_models(tmp_path / "nope.json") == []


def test_load_valid(tmp_path):
    p = _write_models(
        tmp_path,
        [
            {"id": "a", "slug": "x/a", "display_name": "A"},
            {"id": "b", "slug": "x/b", "display_name": "B", "description": "fast"},
        ],
    )
    entries = load_models(p)
    assert [e.id for e in entries] == ["a", "b"]
    assert entries[1].description == "fast"
    assert entries[1].is_enabled is True


def test_load_rejects_missing_fields(tmp_path):
    p = _write_models(tmp_path, [{"id": "a", "slug": "x/a"}])  # no display_name
    with pytest.raises(ValueError, match="display_name"):
        load_models(p)


def test_load_rejects_duplicate_ids(tmp_path):
    p = _write_models(
        tmp_path,
        [
            {"id": "a", "slug": "x/a", "display_name": "A"},
            {"id": "a", "slug": "x/b", "display_name": "B"},
        ],
    )
    with pytest.raises(ValueError, match="Duplicate model id"):
        load_models(p)


def test_load_rejects_duplicate_slugs(tmp_path):
    p = _write_models(
        tmp_path,
        [
            {"id": "a", "slug": "x/same", "display_name": "A"},
            {"id": "b", "slug": "x/same", "display_name": "B"},
        ],
    )
    with pytest.raises(ValueError, match="Duplicate model slug"):
        load_models(p)


def test_load_rejects_non_list(tmp_path):
    p = tmp_path / "models.json"
    p.write_text('{"id": "a"}')
    with pytest.raises(ValueError, match="JSON list"):
        load_models(p)


def test_load_sorts_by_sort_order_then_display_name(tmp_path):
    p = _write_models(
        tmp_path,
        [
            {"id": "c", "slug": "x/c", "display_name": "C", "sort_order": 20},
            {"id": "a", "slug": "x/a", "display_name": "A", "sort_order": 10},
            {"id": "b", "slug": "x/b", "display_name": "B", "sort_order": 10},
        ],
    )
    assert [e.id for e in load_models(p)] == ["a", "b", "c"]


def test_load_enabled_models_filters_disabled(tmp_path):
    p = _write_models(
        tmp_path,
        [
            {"id": "a", "slug": "x/a", "display_name": "A", "is_enabled": True},
            {"id": "b", "slug": "x/b", "display_name": "B", "is_enabled": False},
        ],
    )
    assert [m.id for m in load_enabled_models(p)] == ["a"]


def test_find_model_by_slug(tmp_path):
    p = _write_models(tmp_path, [{"id": "a", "slug": "x/a", "display_name": "A"}])
    assert find_model(p, "x/a").display_name == "A"
    assert find_model(p, "x/missing") is None


def test_find_model_missing_file_returns_none(tmp_path):
    assert find_model(tmp_path / "nope.json", "x/a") is None


# ── threading model_slug through submissions ───────────────────────────────


def test_create_submission_stores_model_slug(tmp_path):
    db = tmp_path / "app.db"
    init_db(db)
    insert_or_update_round(db, _round())
    create_submission(db, "r1", "Team A", "p", max_attempts=3, model_slug="x/a")
    [s] = get_team_submissions(db, "r1", "Team A")
    assert s.model_slug == "x/a"


def test_choose_keeps_model_slug_on_submission(tmp_path):
    db = tmp_path / "app.db"
    init_db(db)
    insert_or_update_round(db, _round())
    sid = create_submission(db, "r1", "Team A", "p", max_attempts=3, model_slug="x/a")
    update_submission_status(db, sid, "completed", image_path="x.png")
    choose_submission(db, sid)
    [sub] = get_submissions_for_round(db, "r1")
    assert sub.model_slug == "x/a"


def test_submission_model_slug_defaults_to_none(tmp_path):
    db = tmp_path / "app.db"
    init_db(db)
    insert_or_update_round(db, _round())
    create_submission(db, "r1", "Team A", "p", max_attempts=3)
    [s] = get_team_submissions(db, "r1", "Team A")
    assert s.model_slug is None


# ── generation start_generation honors model_slug ───────────────────────────


def test_start_generation_uses_provided_model_slug(tmp_path, monkeypatch):
    from unittest.mock import MagicMock

    from genai_cv_game.config import AppSettings
    from genai_cv_game.generation import start_generation

    fake_prediction = MagicMock()
    fake_prediction.id = "pred_abc"
    fake_client = MagicMock()
    fake_client.predictions.create.return_value = fake_prediction
    monkeypatch.setattr(
        "genai_cv_game.generation.replicate.Client", lambda api_token: fake_client
    )
    captured = {}

    def fake_resolve(client, model):
        captured["model"] = model
        return "v-from-" + model

    monkeypatch.setattr("genai_cv_game.generation._resolve_version", fake_resolve)

    s = AppSettings(
        app_title="T",
        replicate_api_token="tok",
        instructor_passcode="x",
        default_replicate_model="default/model",
        db_path=tmp_path / "app.db",
        rounds_path=tmp_path / "rounds.json",
        models_path=tmp_path / "models.json",
        generated_dir=tmp_path / "generated",
        assets_dir=tmp_path / "assets",
        use_stub_generation=False,
    )
    start_generation("p", "r1", "sub1", s, model_slug="x/chosen")
    assert captured["model"] == "x/chosen"


def test_start_generation_falls_back_to_default_model_when_slug_missing(
    tmp_path, monkeypatch
):
    from unittest.mock import MagicMock

    from genai_cv_game.config import AppSettings
    from genai_cv_game.generation import start_generation

    fake_prediction = MagicMock()
    fake_prediction.id = "pred_abc"
    fake_client = MagicMock()
    fake_client.predictions.create.return_value = fake_prediction
    monkeypatch.setattr(
        "genai_cv_game.generation.replicate.Client", lambda api_token: fake_client
    )
    captured = {}

    def fake_resolve(client, model):
        captured["model"] = model
        return "v"

    monkeypatch.setattr("genai_cv_game.generation._resolve_version", fake_resolve)

    s = AppSettings(
        app_title="T",
        replicate_api_token="tok",
        instructor_passcode="x",
        default_replicate_model="default/model",
        db_path=tmp_path / "app.db",
        rounds_path=tmp_path / "rounds.json",
        models_path=tmp_path / "models.json",
        generated_dir=tmp_path / "generated",
        assets_dir=tmp_path / "assets",
        use_stub_generation=False,
    )
    start_generation("p", "r1", "sub1", s)
    assert captured["model"] == "default/model"


def test_start_generation_errors_when_no_model_anywhere(tmp_path):
    from genai_cv_game.config import AppSettings
    from genai_cv_game.generation import start_generation

    s = AppSettings(
        app_title="T",
        replicate_api_token="tok",
        instructor_passcode="x",
        default_replicate_model=None,
        db_path=tmp_path / "app.db",
        rounds_path=tmp_path / "rounds.json",
        models_path=tmp_path / "models.json",
        generated_dir=tmp_path / "generated",
        assets_dir=tmp_path / "assets",
        use_stub_generation=False,
    )
    with pytest.raises(RuntimeError, match="model"):
        start_generation("p", "r1", "sub1", s, model_slug=None)
