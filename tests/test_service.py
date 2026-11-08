"""Tests for the UI-free generation workflow in `service.py`."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from genai_cv_game import service
from genai_cv_game.config import AppSettings
from genai_cv_game.db import (
    BudgetReachedError,
    get_user_generations,
    init_db,
    insert_or_update_task,
)
from genai_cv_game.models import Generation, ModelEntry, Task

PLACEHOLDER = Path("assets/placeholder/stub.png")


def _settings(tmp_path: Path, stub: bool = True, budget: int = 5) -> AppSettings:
    s = AppSettings(
        app_title="T",
        replicate_api_token=None if stub else "tok",
        app_passcode="x",
        instructor_passcode="x",
        default_replicate_model=None,
        db_path=tmp_path / "app.db",
        tasks_path=tmp_path / "tasks.json",
        models_path=tmp_path / "models.json",
        generated_dir=tmp_path / "generated",
        assets_dir=tmp_path / "assets",
        use_stub_generation=stub,
        generation_budget=budget,
    )
    (s.assets_dir / "placeholder").mkdir(parents=True)
    (s.assets_dir / "placeholder" / "stub.png").write_bytes(PLACEHOLDER.read_bytes())
    init_db(s.db_path)
    return s


def _task(s: AppSettings, mode: str = "text2img", **kw) -> Task:
    task = Task(id="t1", title="T", description="d", mode=mode, **kw)
    insert_or_update_task(s.db_path, task)
    return task


def _model(slug="a/b", seed=False, field="image_input") -> ModelEntry:
    return ModelEntry(
        id=slug,
        slug=slug,
        display_name=slug.upper(),
        supports_seed=seed,
        supports_image_input=True,
        image_input_field=field,
    )


# ── pick_seed / budget helpers ───────────────────────────────────────────────


def test_pick_seed_only_for_seed_models():
    assert service.pick_seed(None, 5) is None
    assert service.pick_seed(_model(seed=False), 5) is None
    assert service.pick_seed(_model(seed=True), 5) == 5
    assert isinstance(service.pick_seed(_model(seed=True), None), int)


def test_remaining_budget_ignores_failed():
    gens = [
        Generation(
            id=str(i),
            task_id="t",
            user_name="u",
            prompt="p",
            status=st,
            created_at="",
            updated_at="",
        )
        for i, st in enumerate(["completed", "failed", "pending"])
    ]
    assert service.live_count(gens) == 2
    assert service.remaining_budget(gens, 3) == 1
    assert service.remaining_budget(gens, 1) == 0


# ── start_single_generation ──────────────────────────────────────────────────


def test_single_generation_stub_stores_seed(tmp_path):
    s = _settings(tmp_path)
    task = _task(s)
    gid = service.start_single_generation(
        s, task, "Alice", "p", _model(seed=True), seed=42
    )
    (row,) = get_user_generations(s.db_path, "t1", "Alice")
    assert row.id == gid and row.seed == 42 and row.prediction_id.startswith("stub:")


def test_single_generation_upload_mode_requires_upload(tmp_path):
    s = _settings(tmp_path)
    task = _task(s, mode="explore")
    with pytest.raises(service.GenerationError, match="upload"):
        service.start_single_generation(s, task, "Alice", "p", _model())
    assert get_user_generations(s.db_path, "t1", "Alice") == []


def test_single_generation_saves_upload(tmp_path):
    s = _settings(tmp_path)
    task = _task(s, mode="explore")
    gid = service.start_single_generation(
        s, task, "Alice", "p", _model(), upload=PLACEHOLDER.read_bytes()
    )
    saved = list((s.generated_dir / "t1").glob(f"{gid}_input.*"))
    assert len(saved) == 1


def test_single_generation_budget(tmp_path):
    s = _settings(tmp_path, budget=1)
    task = _task(s)
    service.start_single_generation(s, task, "Alice", "p", None)
    with pytest.raises(BudgetReachedError):
        service.start_single_generation(s, task, "Alice", "p", None)


def test_single_generation_start_failure_marks_row_failed(tmp_path, monkeypatch):
    s = _settings(tmp_path)
    task = _task(s)
    monkeypatch.setattr(
        service, "start_generation", MagicMock(side_effect=RuntimeError("boom"))
    )
    with pytest.raises(service.GenerationError, match="boom"):
        service.start_single_generation(s, task, "Alice", "p", None)
    (row,) = get_user_generations(s.db_path, "t1", "Alice")
    assert row.status == "failed" and "boom" in row.error_message


def test_single_generation_passes_model_image_field(tmp_path, monkeypatch):
    s = _settings(tmp_path)
    img = tmp_path / "src.png"
    img.write_bytes(b"x")
    task = _task(s, mode="edit", input_image_paths=[str(img)])
    fake = MagicMock(return_value="pred")
    monkeypatch.setattr(service, "start_generation", fake)
    service.start_single_generation(s, task, "Alice", "p", _model(field="input_images"))
    kwargs = fake.call_args.kwargs
    assert kwargs["image_input_field"] == "input_images"
    assert kwargs["image_input_paths"] == [img]


# ── start_comparison_round / group_rounds ────────────────────────────────────


def test_comparison_round_shares_batch_and_seed(tmp_path):
    s = _settings(tmp_path)
    task = _task(s, mode="comparison")
    models = [
        _model("a/1", seed=True),
        _model("a/2", seed=False),
        _model("a/3", seed=True),
    ]
    created, errors = service.start_comparison_round(
        s, task, "Alice", "p", models, seed=7
    )
    assert (created, errors) == (3, [])
    rows = get_user_generations(s.db_path, "t1", "Alice")
    assert len({r.batch_id for r in rows}) == 1
    assert [r.seed for r in rows] == [7, None, 7]


def test_comparison_round_stops_at_budget(tmp_path):
    s = _settings(tmp_path, budget=2)
    task = _task(s, mode="comparison")
    created, errors = service.start_comparison_round(
        s, task, "Alice", "p", [_model("a/1"), _model("a/2"), _model("a/3")]
    )
    assert created == 2 and len(errors) == 1


def test_comparison_round_one_failure_does_not_abort(tmp_path, monkeypatch):
    s = _settings(tmp_path)
    task = _task(s, mode="comparison")
    calls = iter([RuntimeError("down"), "pred2"])

    def fake_start(*a, **kw):
        result = next(calls)
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(service, "start_generation", fake_start)
    created, errors = service.start_comparison_round(
        s, task, "Alice", "p", [_model("a/1"), _model("a/2")]
    )
    assert created == 2 and errors == ["A/1: down"]
    statuses = sorted(r.status for r in get_user_generations(s.db_path, "t1", "Alice"))
    assert statuses == ["failed", "pending"]


def test_group_rounds_newest_first(tmp_path):
    def g(i, batch, ts):
        return Generation(
            id=i,
            task_id="t",
            user_name="u",
            prompt="p",
            status="completed",
            batch_id=batch,
            created_at=ts,
            updated_at=ts,
        )

    rounds = service.group_rounds(
        [g("1", "A", "1"), g("2", "A", "1"), g("3", None, "2"), g("4", "B", "3")]
    )
    assert [[x.id for x in r] for r in rounds] == [["4"], ["3"], ["1", "2"]]


# ── Admin budget override ────────────────────────────────────────────────────


def test_budget_override_round_trip(tmp_path):
    from genai_cv_game.db import get_budget_override, set_budget_override

    s = _settings(tmp_path, budget=5)
    assert get_budget_override(s.db_path) is None
    assert service.generation_budget(s) == 5
    set_budget_override(s.db_path, 12)
    assert get_budget_override(s.db_path) == 12
    assert service.generation_budget(s) == 12
    set_budget_override(s.db_path, None)
    assert service.generation_budget(s) == 5
    with pytest.raises(ValueError):
        set_budget_override(s.db_path, 0)


def test_raised_budget_lets_student_continue(tmp_path):
    from genai_cv_game.db import set_budget_override

    s = _settings(tmp_path, budget=1)
    task = _task(s)
    service.start_single_generation(s, task, "Alice", "p", None)
    with pytest.raises(BudgetReachedError):
        service.start_single_generation(s, task, "Alice", "p", None)
    set_budget_override(s.db_path, 2)
    service.start_single_generation(s, task, "Alice", "p", None)
    created, errors = service.start_comparison_round(
        s, task, "Alice", "p", [_model("a/1")]
    )
    assert created == 0 and errors  # new limit of 2 reached again


# ── Prepared inputs for upload-mode tasks ("I want a refund!") ───────────────


def _refund_task(s, tmp_path):
    receipt = tmp_path / "receipt.jpg"
    receipt.write_bytes(PLACEHOLDER.read_bytes())
    return _task(s, mode="explore", input_image_paths=[str(receipt)]), receipt


def test_prepared_input_is_sent_and_recorded(tmp_path, monkeypatch):
    s = _settings(tmp_path)
    task, receipt = _refund_task(s, tmp_path)
    fake = MagicMock(return_value="pred")
    monkeypatch.setattr(service, "start_generation", fake)
    service.start_single_generation(
        s, task, "Alice", "change total", _model(), prepared_input=str(receipt)
    )
    assert fake.call_args.kwargs["image_input_paths"] == [receipt]
    (row,) = get_user_generations(s.db_path, "t1", "Alice")
    assert row.input_image_path == str(receipt)


def test_upload_wins_over_prepared_and_is_recorded(tmp_path):
    s = _settings(tmp_path)
    task, receipt = _refund_task(s, tmp_path)
    gid = service.start_single_generation(
        s,
        task,
        "Alice",
        "p",
        _model(),
        upload=PLACEHOLDER.read_bytes(),
        prepared_input=str(receipt),
    )
    (row,) = get_user_generations(s.db_path, "t1", "Alice")
    assert f"{gid}_input." in row.input_image_path  # saved upload, not the receipt


def test_prepared_input_must_belong_to_task(tmp_path):
    s = _settings(tmp_path)
    task, _ = _refund_task(s, tmp_path)
    with pytest.raises(service.GenerationError, match="not one of"):
        service.start_single_generation(
            s, task, "Alice", "p", _model(), prepared_input="/etc/passwd"
        )
    with pytest.raises(service.GenerationError, match="choose or upload"):
        service.start_single_generation(s, task, "Alice", "p", _model())
    assert get_user_generations(s.db_path, "t1", "Alice") == []


def test_fixed_input_recorded_for_edit_tasks(tmp_path):
    s = _settings(tmp_path)
    img = tmp_path / "src.png"
    img.write_bytes(PLACEHOLDER.read_bytes())
    task = _task(s, mode="edit", input_image_paths=[str(img)])
    service.start_single_generation(s, task, "Alice", "p", _model())
    (row,) = get_user_generations(s.db_path, "t1", "Alice")
    assert row.input_image_path == str(img)


def test_input_label():
    assert service.input_label("assets/x/food_with_bite.jpg") == "Food with bite"
    assert service.input_label("receipt.png") == "Receipt"
