"""Tests for the student-view generation reconciliation logic.

Covers the regression where pending in-flight generations must not be marked
failed while they are still actually running, but should be:
  - completed if the image file lands on disk,
  - failed once the prediction backend reports failure or the timeout passes.
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path

from genai_cv_game.config import AppSettings
from genai_cv_game.db import (
    create_generation,
    get_user_generations,
    init_db,
    insert_or_update_task,
    set_generation_prediction,
)
from genai_cv_game.models import Task
from genai_cv_game.ui.student import _PENDING_TIMEOUT_SECONDS, _reconcile_generation


def _settings(tmp_path: Path) -> AppSettings:
    return AppSettings(
        app_title="Test",
        replicate_api_token=None,
        app_passcode="x",
        instructor_passcode="x",
        default_replicate_model=None,
        db_path=tmp_path / "app.db",
        tasks_path=tmp_path / "tasks.json",
        models_path=tmp_path / "models.json",
        generated_dir=tmp_path / "generated",
        assets_dir=tmp_path / "assets",
        use_stub_generation=True,
        generation_budget=3,
    )


def _setup(tmp_path: Path):
    s = _settings(tmp_path)
    init_db(s.db_path)
    insert_or_update_task(
        s.db_path, Task(id="t1", title="T", description="d", mode="business")
    )
    gen_id = create_generation(
        s.db_path, "t1", "Alice", "prompt", s.generation_budget
    )
    gen = get_user_generations(s.db_path, "t1", "Alice")[0]
    return s, gen, gen_id


def _shift_updated_at(db_path: Path, gen_id: str, seconds_ago: int) -> None:
    import sqlite3

    ts = (datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)).isoformat()
    conn = sqlite3.connect(db_path)
    conn.execute("UPDATE generations SET updated_at=? WHERE id=?", (ts, gen_id))
    conn.commit()
    conn.close()


def test_fresh_pending_stays_pending(tmp_path):
    s, gen, _ = _setup(tmp_path)
    result = _reconcile_generation(gen, s)
    assert result.status == "pending"


def test_pending_with_existing_image_recovers_to_completed(tmp_path):
    s, gen, gen_id = _setup(tmp_path)
    img = s.generated_dir / "t1" / f"{gen_id}.png"
    img.parent.mkdir(parents=True, exist_ok=True)
    img.write_bytes(b"\x89PNG fake")

    result = _reconcile_generation(gen, s)
    assert result.status == "completed"
    assert result.image_path == str(img)


def test_old_pending_without_image_is_failed(tmp_path):
    s, _, gen_id = _setup(tmp_path)
    _shift_updated_at(s.db_path, gen_id, _PENDING_TIMEOUT_SECONDS + 10)
    gen = get_user_generations(s.db_path, "t1", "Alice")[0]

    result = _reconcile_generation(gen, s)
    assert result.status == "failed"
    assert "timed out" in (result.error_message or "").lower()


def test_old_pending_with_image_still_recovers(tmp_path):
    """Recovery beats expiry: an existing image trumps a stale timestamp."""
    s, _, gen_id = _setup(tmp_path)
    img = s.generated_dir / "t1" / f"{gen_id}.png"
    img.parent.mkdir(parents=True, exist_ok=True)
    img.write_bytes(b"\x89PNG fake")
    _shift_updated_at(s.db_path, gen_id, _PENDING_TIMEOUT_SECONDS + 10)
    gen = get_user_generations(s.db_path, "t1", "Alice")[0]

    result = _reconcile_generation(gen, s)
    assert result.status == "completed"


def test_pending_with_prediction_id_polls_and_succeeds(tmp_path, monkeypatch):
    """When prediction_id is set, reconcile delegates to poll_generation."""
    from genai_cv_game.generation import GenerationResult

    s, _, gen_id = _setup(tmp_path)
    set_generation_prediction(s.db_path, gen_id, "pred_xyz")
    gen = get_user_generations(s.db_path, "t1", "Alice")[0]

    img_path = s.generated_dir / "t1" / f"{gen_id}.png"
    img_path.parent.mkdir(parents=True, exist_ok=True)
    img_path.write_bytes(b"\x89PNG fake")

    monkeypatch.setattr(
        "genai_cv_game.ui.student.poll_generation",
        lambda *a, **kw: GenerationResult(status="succeeded", image_path=str(img_path)),
    )

    result = _reconcile_generation(gen, s)
    assert result.status == "completed"
    assert result.image_path == str(img_path)


def test_pending_with_prediction_id_still_processing_stays_pending(
    tmp_path, monkeypatch
):
    from genai_cv_game.generation import GenerationResult

    s, _, gen_id = _setup(tmp_path)
    set_generation_prediction(s.db_path, gen_id, "pred_xyz")
    gen = get_user_generations(s.db_path, "t1", "Alice")[0]

    monkeypatch.setattr(
        "genai_cv_game.ui.student.poll_generation",
        lambda *a, **kw: GenerationResult(status="pending"),
    )

    result = _reconcile_generation(gen, s)
    assert result.status == "pending"


def test_pending_with_prediction_id_failed_marks_failed(tmp_path, monkeypatch):
    from genai_cv_game.generation import GenerationResult

    s, _, gen_id = _setup(tmp_path)
    set_generation_prediction(s.db_path, gen_id, "pred_xyz")
    gen = get_user_generations(s.db_path, "t1", "Alice")[0]

    monkeypatch.setattr(
        "genai_cv_game.ui.student.poll_generation",
        lambda *a, **kw: GenerationResult(status="failed", error="model died"),
    )

    result = _reconcile_generation(gen, s)
    assert result.status == "failed"
    assert result.error_message == "model died"
