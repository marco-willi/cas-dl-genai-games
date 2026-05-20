from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Generator

from genai_cv_game.models import Generation, Task
from genai_cv_game.utils import new_id, now_utc

_ALLOWED_GENERATION_STATUSES = frozenset({"pending", "completed", "failed"})
_API_ENABLED_KEY = "api_enabled"


@contextmanager
def get_connection(db_path: Path) -> Generator[sqlite3.Connection, None, None]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(db_path: Path) -> None:
    create_tables(db_path)


def create_tables(db_path: Path) -> None:
    with get_connection(db_path) as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS tasks (
                id                 TEXT PRIMARY KEY,
                title              TEXT NOT NULL,
                description        TEXT NOT NULL,
                mode               TEXT NOT NULL,
                target_image_path  TEXT,
                input_image_paths  TEXT NOT NULL DEFAULT '[]',
                is_available       INTEGER NOT NULL DEFAULT 1,
                created_at         TEXT NOT NULL,
                updated_at         TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS generations (
                id            TEXT PRIMARY KEY,
                task_id       TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
                user_name     TEXT NOT NULL,
                prompt        TEXT NOT NULL,
                image_path    TEXT,
                status        TEXT NOT NULL,
                error_message TEXT,
                prediction_id TEXT,
                model_slug    TEXT,
                in_gallery    INTEGER NOT NULL DEFAULT 0,
                created_at    TEXT NOT NULL,
                updated_at    TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS app_settings (
                key        TEXT PRIMARY KEY,
                value      TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_generations_task_user
                ON generations (task_id, LOWER(user_name));
            CREATE UNIQUE INDEX IF NOT EXISTS idx_generations_gallery_task_user
                ON generations (task_id, LOWER(user_name)) WHERE in_gallery=1;
        """)
        conn.execute(
            "INSERT OR IGNORE INTO app_settings (key, value, updated_at) "
            "VALUES (?, '1', ?)",
            (_API_ENABLED_KEY, now_utc()),
        )


# ── Tasks ───────────────────────────────────────────────────────────────────


def insert_or_update_task(db_path: Path, task: Task) -> None:
    """Upsert a task's definitional columns, preserving is_available."""
    ts = now_utc()
    with get_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO tasks (
                id, title, description, mode,
                target_image_path, input_image_paths,
                created_at, updated_at
            )
            VALUES (
                :id, :title, :description, :mode,
                :target_image_path, :input_image_paths,
                :ts, :ts
            )
            ON CONFLICT(id) DO UPDATE SET
                title             = excluded.title,
                description       = excluded.description,
                mode              = excluded.mode,
                target_image_path = excluded.target_image_path,
                input_image_paths = excluded.input_image_paths,
                updated_at        = excluded.updated_at
            """,
            {
                "id": task.id,
                "title": task.title,
                "description": task.description,
                "mode": task.mode,
                "target_image_path": task.target_image_path,
                "input_image_paths": json.dumps(task.input_image_paths),
                "ts": ts,
            },
        )


def get_all_tasks(db_path: Path) -> list[Task]:
    with get_connection(db_path) as conn:
        rows = conn.execute("SELECT * FROM tasks ORDER BY created_at").fetchall()
    return [_row_to_task(r) for r in rows]


def get_available_tasks(db_path: Path) -> list[Task]:
    with get_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM tasks WHERE is_available=1 ORDER BY created_at"
        ).fetchall()
    return [_row_to_task(r) for r in rows]


def get_task(db_path: Path, task_id: str) -> Task | None:
    with get_connection(db_path) as conn:
        row = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
    return _row_to_task(row) if row else None


def set_task_availability(db_path: Path, task_id: str, is_available: bool) -> None:
    ts = now_utc()
    with get_connection(db_path) as conn:
        exists = conn.execute("SELECT 1 FROM tasks WHERE id=?", (task_id,)).fetchone()
        if not exists:
            raise ValueError(f"Unknown task id: {task_id!r}")
        conn.execute(
            "UPDATE tasks SET is_available=?, updated_at=? WHERE id=?",
            (int(is_available), ts, task_id),
        )


# ── Generations ───────────────────────────────────────────────────────────────


class BudgetReachedError(Exception):
    """A user has used all of their generation budget for this task."""


def create_generation(
    db_path: Path,
    task_id: str,
    user_name: str,
    prompt: str,
    generation_budget: int,
    model_slug: str | None = None,
) -> str:
    """Create a new pending generation for a user on a task.

    Budget counts only non-failed rows (pending + completed); failed rows are
    discardable and do not consume a slot.

    Raises:
        ValueError: user_name is blank or generation_budget < 1.
        BudgetReachedError: user already has `generation_budget` non-failed rows.
    """
    normalized = user_name.strip()
    if not normalized:
        raise ValueError("user_name must not be empty")
    if generation_budget < 1:
        raise ValueError("generation_budget must be >= 1")
    gen_id = new_id()
    ts = now_utc()
    with get_connection(db_path) as conn:
        row = conn.execute(
            """
            SELECT COUNT(*) AS live
            FROM generations
            WHERE task_id=? AND LOWER(user_name)=LOWER(?) AND status<>'failed'
            """,
            (task_id, normalized),
        ).fetchone()
        if row["live"] >= generation_budget:
            raise BudgetReachedError(
                f"'{normalized}' has used all {generation_budget} generations "
                "for this task."
            )
        conn.execute(
            """
            INSERT INTO generations
                (id, task_id, user_name, prompt, status, model_slug,
                 in_gallery, created_at, updated_at)
            VALUES (?, ?, ?, ?, 'pending', ?, 0, ?, ?)
            """,
            (gen_id, task_id, normalized, prompt, model_slug, ts, ts),
        )
    return gen_id


def set_generation_prediction(
    db_path: Path, generation_id: str, prediction_id: str
) -> None:
    ts = now_utc()
    with get_connection(db_path) as conn:
        conn.execute(
            "UPDATE generations SET prediction_id=?, updated_at=? WHERE id=?",
            (prediction_id, ts, generation_id),
        )


def update_generation_status(
    db_path: Path,
    generation_id: str,
    status: str,
    image_path: str | None = None,
    error_message: str | None = None,
) -> None:
    if status not in _ALLOWED_GENERATION_STATUSES:
        raise ValueError(
            f"Invalid status {status!r}. Must be one of: "
            f"{sorted(_ALLOWED_GENERATION_STATUSES)}"
        )
    ts = now_utc()
    with get_connection(db_path) as conn:
        conn.execute(
            """
            UPDATE generations
            SET status=?, image_path=?, error_message=?, updated_at=?
            WHERE id=?
            """,
            (status, image_path, error_message, ts, generation_id),
        )


def submit_to_gallery(db_path: Path, generation_id: str) -> None:
    """Mark a completed generation as the user's single gallery entry for the task.

    Clears any other in_gallery row for the same (task, user) so exactly one
    stays — but does NOT delete sibling generations. Raises ValueError if the
    row is missing or not completed.
    """
    ts = now_utc()
    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT task_id, user_name, status FROM generations WHERE id=?",
            (generation_id,),
        ).fetchone()
        if not row:
            raise ValueError(f"Unknown generation id: {generation_id!r}")
        if row["status"] != "completed":
            raise ValueError(
                f"Generation {generation_id!r} has status {row['status']!r}; "
                "only completed generations can be shown in the gallery."
            )
        conn.execute(
            """
            UPDATE generations SET in_gallery=0, updated_at=?
            WHERE task_id=? AND LOWER(user_name)=LOWER(?) AND id<>?
            """,
            (ts, row["task_id"], row["user_name"], generation_id),
        )
        conn.execute(
            "UPDATE generations SET in_gallery=1, updated_at=? WHERE id=?",
            (ts, generation_id),
        )


def remove_from_gallery(db_path: Path, generation_id: str) -> None:
    ts = now_utc()
    with get_connection(db_path) as conn:
        conn.execute(
            "UPDATE generations SET in_gallery=0, updated_at=? WHERE id=?",
            (ts, generation_id),
        )


def get_gallery_generations(db_path: Path, task_id: str) -> list[Generation]:
    """Return the gallery entries for a task — one per user that has chosen."""
    with get_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM generations WHERE task_id=? AND in_gallery=1 "
            "ORDER BY created_at",
            (task_id,),
        ).fetchall()
    return [_row_to_generation(r) for r in rows]


def get_user_generations(
    db_path: Path, task_id: str, user_name: str
) -> list[Generation]:
    """Return all generations for a single user on a task."""
    needle = user_name.strip()
    with get_connection(db_path) as conn:
        rows = conn.execute(
            """
            SELECT * FROM generations
            WHERE task_id=? AND LOWER(user_name)=LOWER(?)
            ORDER BY created_at
            """,
            (task_id, needle),
        ).fetchall()
    return [_row_to_generation(r) for r in rows]


def delete_generation(db_path: Path, generation_id: str) -> None:
    with get_connection(db_path) as conn:
        conn.execute("DELETE FROM generations WHERE id=?", (generation_id,))


def delete_user_generations(db_path: Path, task_id: str, user_name: str) -> None:
    with get_connection(db_path) as conn:
        conn.execute(
            "DELETE FROM generations WHERE task_id=? AND LOWER(user_name)=LOWER(?)",
            (task_id, user_name.strip()),
        )


def reset_task_generations(db_path: Path, task_id: str) -> None:
    """Delete every generation for one task (per-task gallery reset)."""
    with get_connection(db_path) as conn:
        conn.execute("DELETE FROM generations WHERE task_id=?", (task_id,))


def reset_all_generations(db_path: Path) -> None:
    """Delete every generation across all tasks (global gallery reset)."""
    with get_connection(db_path) as conn:
        conn.execute("DELETE FROM generations")


def delete_database(db_path: Path) -> None:
    """Remove the SQLite DB file and its WAL/SHM sidecars.

    Callers are expected to re-run init_db / sync_tasks_from_json afterwards
    so the schema and tasks are restored on the next render.
    """
    for suffix in ("", "-wal", "-shm"):
        sidecar = db_path.with_name(db_path.name + suffix) if suffix else db_path
        if sidecar.exists():
            sidecar.unlink()


# ── App settings ──────────────────────────────────────────────────────────────


def get_setting(db_path: Path, key: str) -> str | None:
    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT value FROM app_settings WHERE key=?", (key,)
        ).fetchone()
    return row["value"] if row else None


def set_setting(db_path: Path, key: str, value: str) -> None:
    ts = now_utc()
    with get_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO app_settings (key, value, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                value      = excluded.value,
                updated_at = excluded.updated_at
            """,
            (key, value, ts),
        )


def is_api_enabled(db_path: Path) -> bool:
    return get_setting(db_path, _API_ENABLED_KEY) == "1"


def set_api_enabled(db_path: Path, enabled: bool) -> None:
    set_setting(db_path, _API_ENABLED_KEY, "1" if enabled else "0")


# ── Row mappers ───────────────────────────────────────────────────────────────


def _row_to_task(row: sqlite3.Row) -> Task:
    raw_inputs = row["input_image_paths"] or "[]"
    return Task(
        id=row["id"],
        title=row["title"],
        description=row["description"],
        mode=row["mode"],
        target_image_path=row["target_image_path"],
        input_image_paths=json.loads(raw_inputs),
        is_available=bool(row["is_available"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _row_to_generation(row: sqlite3.Row) -> Generation:
    return Generation(
        id=row["id"],
        task_id=row["task_id"],
        user_name=row["user_name"],
        prompt=row["prompt"],
        image_path=row["image_path"],
        status=row["status"],
        error_message=row["error_message"],
        prediction_id=row["prediction_id"],
        model_slug=row["model_slug"],
        in_gallery=bool(row["in_gallery"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )
