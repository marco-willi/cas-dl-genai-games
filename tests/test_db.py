import sqlite3

import pytest

from genai_cv_game.db import (
    create_generation,
    get_all_tasks,
    get_available_tasks,
    get_task,
    init_db,
    insert_or_update_task,
    is_api_enabled,
    set_api_enabled,
    set_task_availability,
    update_generation_status,
)
from genai_cv_game.models import Task


def _task(id="t1", mode="business", **kwargs) -> Task:
    return Task(
        id=id,
        title=f"Task {id}",
        description="desc",
        mode=mode,
        **kwargs,
    )


def test_init_creates_tables(tmp_path):
    db = tmp_path / "app.db"
    init_db(db)

    conn = sqlite3.connect(db)
    tables = {
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    assert {"tasks", "generations", "app_settings"} <= tables
    assert "rounds" not in tables
    assert "submissions" not in tables
    assert "votes" not in tables
    assert conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 0


def test_init_seeds_api_enabled(tmp_path):
    db = tmp_path / "app.db"
    init_db(db)
    assert is_api_enabled(db) is True


def test_insert_and_get_task(tmp_path):
    db = tmp_path / "app.db"
    init_db(db)
    insert_or_update_task(db, _task("t1", mode="match"))
    tasks = get_all_tasks(db)
    assert len(tasks) == 1
    assert tasks[0].id == "t1"
    assert tasks[0].mode == "match"
    assert tasks[0].is_available is True
    assert tasks[0].created_at != ""


def test_task_input_image_paths_roundtrip(tmp_path):
    db = tmp_path / "app.db"
    init_db(db)
    insert_or_update_task(
        db,
        _task(
            "edit1",
            mode="edit",
            input_image_paths=["assets/input_images/edit/edit1.jpg"],
        ),
    )
    [t] = get_all_tasks(db)
    assert t.mode == "edit"
    assert t.input_image_paths == ["assets/input_images/edit/edit1.jpg"]


def test_task_input_image_paths_default_empty(tmp_path):
    db = tmp_path / "app.db"
    init_db(db)
    insert_or_update_task(db, _task("b1", mode="business"))
    [t] = get_all_tasks(db)
    assert t.input_image_paths == []


def test_upsert_task_preserves_availability(tmp_path):
    db = tmp_path / "app.db"
    init_db(db)
    insert_or_update_task(db, _task("t1"))
    set_task_availability(db, "t1", False)

    insert_or_update_task(
        db, Task(id="t1", title="New Title", description="desc", mode="business")
    )
    tasks = get_all_tasks(db)
    assert tasks[0].title == "New Title"
    assert tasks[0].is_available is False


def test_get_available_tasks_filters_unavailable(tmp_path):
    db = tmp_path / "app.db"
    init_db(db)
    insert_or_update_task(db, _task("t1"))
    insert_or_update_task(db, _task("t2"))
    set_task_availability(db, "t2", False)

    available = get_available_tasks(db)
    assert {t.id for t in available} == {"t1"}


def test_get_task_returns_none_for_unknown(tmp_path):
    db = tmp_path / "app.db"
    init_db(db)
    assert get_task(db, "missing") is None


def test_set_task_availability_rejects_unknown_id(tmp_path):
    db = tmp_path / "app.db"
    init_db(db)
    with pytest.raises(ValueError, match="Unknown task id"):
        set_task_availability(db, "does_not_exist", True)


def test_set_api_enabled_toggles(tmp_path):
    db = tmp_path / "app.db"
    init_db(db)
    set_api_enabled(db, False)
    assert is_api_enabled(db) is False
    set_api_enabled(db, True)
    assert is_api_enabled(db) is True


def test_update_generation_status_rejects_invalid_status(tmp_path):
    db = tmp_path / "app.db"
    init_db(db)
    insert_or_update_task(db, _task("t1"))
    gen_id = create_generation(db, "t1", "Alice", "p", generation_budget=3)
    with pytest.raises(ValueError, match="Invalid status"):
        update_generation_status(db, gen_id, "in_progress")
