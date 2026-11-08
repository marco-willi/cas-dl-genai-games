"""Tests for the generations table — budget, gallery membership, resets."""

import pytest

from genai_cv_game.db import (
    BudgetReachedError,
    create_generation,
    delete_generation,
    delete_user_generations,
    get_gallery_generations,
    get_user_generations,
    init_db,
    insert_or_update_task,
    remove_from_gallery,
    reset_all_generations,
    reset_task_generations,
    submit_to_gallery,
    update_generation_status,
)
from genai_cv_game.models import Task


def _task(tid="t1") -> Task:
    return Task(id=tid, title=f"T {tid}", description="d", mode="business")


def _setup(tmp_path, *tids):
    db = tmp_path / "app.db"
    init_db(db)
    for tid in tids or ("t1",):
        insert_or_update_task(db, _task(tid))
    return db


def test_create_generation_returns_id_and_pending(tmp_path):
    db = _setup(tmp_path)
    gid = create_generation(db, "t1", "Alice", "p", generation_budget=3)
    rows = get_user_generations(db, "t1", "Alice")
    assert len(rows) == 1
    assert rows[0].id == gid
    assert rows[0].status == "pending"
    assert rows[0].in_gallery is False
    assert rows[0].user_name == "Alice"
    assert rows[0].image_path is None
    assert rows[0].prediction_id is None


def test_budget_blocks_when_reached(tmp_path):
    db = _setup(tmp_path)
    create_generation(db, "t1", "Alice", "p1", generation_budget=2)
    create_generation(db, "t1", "Alice", "p2", generation_budget=2)
    with pytest.raises(BudgetReachedError, match="all 2 generations"):
        create_generation(db, "t1", "Alice", "p3", generation_budget=2)


def test_failed_generation_does_not_consume_budget(tmp_path):
    db = _setup(tmp_path)
    g1 = create_generation(db, "t1", "Alice", "p1", generation_budget=2)
    create_generation(db, "t1", "Alice", "p2", generation_budget=2)
    update_generation_status(db, g1, "failed", error_message="boom")
    # g1 failed, so only one live row remains — a new one is allowed
    g3 = create_generation(db, "t1", "Alice", "p3", generation_budget=2)
    assert g3 is not None


def test_budget_case_insensitive(tmp_path):
    db = _setup(tmp_path)
    create_generation(db, "t1", "Alice", "p1", generation_budget=1)
    with pytest.raises(BudgetReachedError):
        create_generation(db, "t1", "alice", "p2", generation_budget=1)


def test_create_generation_strips_user_name(tmp_path):
    db = _setup(tmp_path)
    create_generation(db, "t1", "  Alice  ", "p1", generation_budget=2)
    rows = get_user_generations(db, "t1", "Alice")
    assert len(rows) == 1
    assert rows[0].user_name == "Alice"


def test_create_generation_rejects_empty_user(tmp_path):
    db = _setup(tmp_path)
    with pytest.raises(ValueError):
        create_generation(db, "t1", "  ", "p", generation_budget=3)


def test_create_generation_rejects_zero_budget(tmp_path):
    db = _setup(tmp_path)
    with pytest.raises(ValueError):
        create_generation(db, "t1", "Alice", "p", generation_budget=0)


def test_fan_out_creates_one_row_per_model(tmp_path):
    # Mirrors the comparison-mode fan-out: one prompt, one row per model.
    db = _setup(tmp_path)
    slugs = [
        "ideogram-ai/ideogram-v3-turbo",
        "black-forest-labs/flux-1.1-pro",
        "bytedance/seedream-4",
    ]
    for slug in slugs:
        create_generation(
            db, "t1", "Alice", "same prompt", generation_budget=30, model_slug=slug
        )
    rows = get_user_generations(db, "t1", "Alice")
    assert len(rows) == 3
    assert {r.model_slug for r in rows} == set(slugs)
    assert {r.prompt for r in rows} == {"same prompt"}


def test_fan_out_respects_budget(tmp_path):
    db = _setup(tmp_path)
    create_generation(db, "t1", "Alice", "p", generation_budget=2, model_slug="m/a")
    create_generation(db, "t1", "Alice", "p", generation_budget=2, model_slug="m/b")
    with pytest.raises(BudgetReachedError):
        create_generation(db, "t1", "Alice", "p", generation_budget=2, model_slug="m/c")


def test_delete_generation(tmp_path):
    db = _setup(tmp_path)
    g1 = create_generation(db, "t1", "Alice", "p1", generation_budget=3)
    g2 = create_generation(db, "t1", "Alice", "p2", generation_budget=3)
    delete_generation(db, g1)
    rows = get_user_generations(db, "t1", "Alice")
    assert [r.id for r in rows] == [g2]


def test_delete_user_generations(tmp_path):
    db = _setup(tmp_path)
    create_generation(db, "t1", "Alice", "p1", generation_budget=3)
    create_generation(db, "t1", "Alice", "p2", generation_budget=3)
    create_generation(db, "t1", "Bob", "px", generation_budget=3)
    delete_user_generations(db, "t1", "Alice")
    assert get_user_generations(db, "t1", "Alice") == []
    assert len(get_user_generations(db, "t1", "Bob")) == 1


def test_submit_to_gallery_marks_one_and_keeps_siblings(tmp_path):
    db = _setup(tmp_path)
    g1 = create_generation(db, "t1", "Alice", "p1", generation_budget=3)
    g2 = create_generation(db, "t1", "Alice", "p2", generation_budget=3)
    update_generation_status(db, g1, "completed", image_path="g1.png")
    update_generation_status(db, g2, "completed", image_path="g2.png")

    submit_to_gallery(db, g2)

    rows = get_user_generations(db, "t1", "Alice")
    # both rows survive
    assert len(rows) == 2
    in_gallery = [r for r in rows if r.in_gallery]
    assert [r.id for r in in_gallery] == [g2]


def test_submit_to_gallery_switches_single_entry(tmp_path):
    db = _setup(tmp_path)
    g1 = create_generation(db, "t1", "Alice", "p1", generation_budget=3)
    g2 = create_generation(db, "t1", "Alice", "p2", generation_budget=3)
    update_generation_status(db, g1, "completed", image_path="g1.png")
    update_generation_status(db, g2, "completed", image_path="g2.png")

    submit_to_gallery(db, g1)
    submit_to_gallery(db, g2)

    gallery = get_gallery_generations(db, "t1")
    assert [g.id for g in gallery] == [g2]


def test_remove_from_gallery(tmp_path):
    db = _setup(tmp_path)
    g1 = create_generation(db, "t1", "Alice", "p1", generation_budget=3)
    update_generation_status(db, g1, "completed", image_path="g1.png")
    submit_to_gallery(db, g1)
    remove_from_gallery(db, g1)
    assert get_gallery_generations(db, "t1") == []


def test_submit_to_gallery_rejects_non_completed(tmp_path):
    db = _setup(tmp_path)
    gid = create_generation(db, "t1", "Alice", "p1", generation_budget=3)
    with pytest.raises(ValueError, match="completed generations"):
        submit_to_gallery(db, gid)


def test_submit_to_gallery_rejects_unknown(tmp_path):
    db = _setup(tmp_path)
    with pytest.raises(ValueError, match="Unknown generation id"):
        submit_to_gallery(db, "nope")


def test_gallery_independent_across_users(tmp_path):
    db = _setup(tmp_path)
    ga = create_generation(db, "t1", "Alice", "p", generation_budget=1)
    update_generation_status(db, ga, "completed", image_path="a.png")
    submit_to_gallery(db, ga)
    gb = create_generation(db, "t1", "Bob", "p", generation_budget=1)
    update_generation_status(db, gb, "completed", image_path="b.png")
    submit_to_gallery(db, gb)

    gallery = get_gallery_generations(db, "t1")
    assert {g.user_name for g in gallery} == {"Alice", "Bob"}


def test_get_gallery_generations_returns_in_gallery_only(tmp_path):
    db = _setup(tmp_path)
    a = create_generation(db, "t1", "Alice", "p", generation_budget=3)
    create_generation(db, "t1", "Bob", "p", generation_budget=3)  # never submitted
    update_generation_status(db, a, "completed", image_path="x.png")
    submit_to_gallery(db, a)

    rows = get_gallery_generations(db, "t1")
    assert [r.id for r in rows] == [a]


def test_reset_task_generations_wipes_one_task(tmp_path):
    db = _setup(tmp_path, "t1", "t2")
    create_generation(db, "t1", "Alice", "p", generation_budget=3)
    create_generation(db, "t2", "Alice", "p", generation_budget=3)
    reset_task_generations(db, "t1")
    assert get_user_generations(db, "t1", "Alice") == []
    assert len(get_user_generations(db, "t2", "Alice")) == 1


def test_reset_all_generations_wipes_everything(tmp_path):
    db = _setup(tmp_path, "t1", "t2")
    create_generation(db, "t1", "Alice", "p", generation_budget=3)
    create_generation(db, "t2", "Bob", "p", generation_budget=3)
    reset_all_generations(db)
    assert get_user_generations(db, "t1", "Alice") == []
    assert get_user_generations(db, "t2", "Bob") == []


def _completed(db, user="Alice", tid="t1"):
    gid = create_generation(db, tid, user, "p", generation_budget=3)
    update_generation_status(db, gid, "completed", image_path="x.png")
    return gid


def test_hide_from_gallery_removes_entry_and_flags_row(tmp_path):
    from genai_cv_game.db import hide_from_gallery

    db = _setup(tmp_path)
    gid = _completed(db)
    submit_to_gallery(db, gid)
    hide_from_gallery(db, gid)
    assert get_gallery_generations(db, "t1") == []
    (row,) = get_user_generations(db, "t1", "Alice")
    assert row.hidden is True
    assert row.in_gallery is False


def test_hidden_generation_cannot_be_reshared(tmp_path):
    from genai_cv_game.db import hide_from_gallery

    db = _setup(tmp_path)
    gid = _completed(db)
    hide_from_gallery(db, gid)
    with pytest.raises(ValueError, match="hidden"):
        submit_to_gallery(db, gid)


def test_hiding_one_generation_leaves_siblings_shareable(tmp_path):
    from genai_cv_game.db import hide_from_gallery

    db = _setup(tmp_path)
    bad = _completed(db)
    good = _completed(db)
    hide_from_gallery(db, bad)
    submit_to_gallery(db, good)
    assert [g.id for g in get_gallery_generations(db, "t1")] == [good]


def test_migration_adds_hidden_column_to_old_db(tmp_path):
    import sqlite3

    db = tmp_path / "old.db"
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE generations (id TEXT PRIMARY KEY, task_id TEXT NOT NULL, "
        "user_name TEXT NOT NULL, prompt TEXT NOT NULL, image_path TEXT, "
        "status TEXT NOT NULL, error_message TEXT, prediction_id TEXT, "
        "model_slug TEXT, in_gallery INTEGER NOT NULL DEFAULT 0, "
        "created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"
    )
    conn.commit()
    conn.close()
    init_db(db)
    insert_or_update_task(db, _task())
    gid = _completed(db)
    (row,) = get_user_generations(db, "t1", "Alice")
    assert row.id == gid and row.hidden is False


# ── Multiple gallery picks (tasks.gallery_picks) ─────────────────────────────


def test_two_picks_kept_third_replaces_oldest(tmp_path):
    import time

    db = _setup(tmp_path)
    g1, g2, g3 = (_completed(db) for _ in range(3))
    submit_to_gallery(db, g1, max_entries=2)
    time.sleep(0.01)
    submit_to_gallery(db, g2, max_entries=2)
    assert {g.id for g in get_gallery_generations(db, "t1")} == {g1, g2}
    time.sleep(0.01)
    submit_to_gallery(db, g3, max_entries=2)
    assert {g.id for g in get_gallery_generations(db, "t1")} == {g2, g3}


def test_resharing_a_pick_is_a_no_op(tmp_path):
    db = _setup(tmp_path)
    g1, g2 = _completed(db), _completed(db)
    submit_to_gallery(db, g1, max_entries=2)
    submit_to_gallery(db, g2, max_entries=2)
    submit_to_gallery(db, g2, max_entries=2)
    assert {g.id for g in get_gallery_generations(db, "t1")} == {g1, g2}


def test_picks_are_per_user(tmp_path):
    db = _setup(tmp_path)
    a = _completed(db, user="Alice")
    b = _completed(db, user="Bob")
    submit_to_gallery(db, a, max_entries=1)
    submit_to_gallery(db, b, max_entries=1)
    assert {g.id for g in get_gallery_generations(db, "t1")} == {a, b}


def test_gallery_picks_stored_on_task(tmp_path):
    from genai_cv_game.db import get_task

    db = tmp_path / "app.db"
    init_db(db)
    insert_or_update_task(
        db, Task(id="y", title="Y", description="d", mode="text2img", gallery_picks=2)
    )
    assert get_task(db, "y").gallery_picks == 2


def test_old_unique_gallery_index_is_dropped(tmp_path):
    import sqlite3

    db = tmp_path / "old.db"
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE generations (id TEXT PRIMARY KEY, task_id TEXT NOT NULL,
            user_name TEXT NOT NULL, prompt TEXT NOT NULL, image_path TEXT,
            status TEXT NOT NULL, error_message TEXT, prediction_id TEXT,
            model_slug TEXT, in_gallery INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
        CREATE UNIQUE INDEX idx_generations_gallery_task_user
            ON generations (task_id, LOWER(user_name)) WHERE in_gallery=1;
        """
    )
    conn.commit()
    conn.close()
    init_db(db)
    insert_or_update_task(db, _task())
    g1, g2 = _completed(db), _completed(db)
    submit_to_gallery(db, g1, max_entries=2)
    submit_to_gallery(db, g2, max_entries=2)  # would violate the old unique index
    assert len(get_gallery_generations(db, "t1")) == 2
