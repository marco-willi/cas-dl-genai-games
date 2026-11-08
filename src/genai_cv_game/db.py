"""All SQLite access. One short-lived connection per call."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from genai_cv_game.models import (
    GENERATION_STATUSES,
    VOTE_LABELS,
    Generation,
    Task,
    VoteImage,
)
from genai_cv_game.utils import new_id, now_utc, parse_utc

_API_ENABLED_KEY = "api_enabled"
_REVEAL_KEY_PREFIX = "reveal:"
_BUDGET_KEY = "generation_budget"


@contextmanager
def get_connection(db_path: Path) -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    # journal_mode=WAL is persistent in the DB file and set once in init_db.
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ── Schema ───────────────────────────────────────────────────────────────────

_SCHEMA = """
    CREATE TABLE IF NOT EXISTS tasks (
        id                 TEXT PRIMARY KEY,
        title              TEXT NOT NULL,
        description        TEXT NOT NULL,
        mode               TEXT NOT NULL,
        nav_title          TEXT,
        section            TEXT,
        icon               TEXT,
        target_image_path  TEXT,
        input_image_paths  TEXT NOT NULL DEFAULT '[]',
        is_available       INTEGER NOT NULL DEFAULT 1,
        sort_order         INTEGER NOT NULL DEFAULT 0,
        gallery_picks      INTEGER NOT NULL DEFAULT 1,
        input_image_labels TEXT NOT NULL DEFAULT '{}',
        allow_text_only    INTEGER NOT NULL DEFAULT 0,
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
        seed          INTEGER,
        batch_id      TEXT,
        input_image_path TEXT,
        in_gallery    INTEGER NOT NULL DEFAULT 0,
        hidden        INTEGER NOT NULL DEFAULT 0,
        created_at    TEXT NOT NULL,
        updated_at    TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS reactions (
        generation_id TEXT NOT NULL REFERENCES generations(id) ON DELETE CASCADE,
        user_name     TEXT NOT NULL,
        created_at    TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS app_settings (
        key        TEXT PRIMARY KEY,
        value      TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS vote_images (
        id         TEXT NOT NULL,
        task_id    TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
        image_path TEXT NOT NULL,
        label      TEXT NOT NULL,
        hint       TEXT NOT NULL DEFAULT '',
        pair       TEXT NOT NULL DEFAULT '',
        sort_order INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        PRIMARY KEY (task_id, id)
    );

    CREATE TABLE IF NOT EXISTS votes (
        id         TEXT PRIMARY KEY,
        task_id    TEXT NOT NULL,
        image_id   TEXT NOT NULL,
        user_name  TEXT NOT NULL,
        vote       TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY (task_id, image_id)
            REFERENCES vote_images (task_id, id) ON DELETE CASCADE
    );

    CREATE INDEX IF NOT EXISTS idx_generations_task_user
        ON generations (task_id, LOWER(user_name));
    -- Gallery picks per (task, user) are limited in code (tasks.gallery_picks);
    -- the old one-pick unique index is dropped from existing databases.
    DROP INDEX IF EXISTS idx_generations_gallery_task_user;
    CREATE INDEX IF NOT EXISTS idx_generations_gallery_task_user_v2
        ON generations (task_id, LOWER(user_name)) WHERE in_gallery=1;
    CREATE UNIQUE INDEX IF NOT EXISTS idx_reactions_gen_user
        ON reactions (generation_id, LOWER(user_name));
    CREATE INDEX IF NOT EXISTS idx_vote_images_task
        ON vote_images (task_id, sort_order);
    CREATE UNIQUE INDEX IF NOT EXISTS idx_votes_image_user
        ON votes (task_id, image_id, LOWER(user_name));
"""

# Columns added after the first release: (table, column, DDL type/default).
# `CREATE TABLE IF NOT EXISTS` leaves existing tables untouched, so older
# databases get these via ALTER TABLE on startup.
_ADDED_COLUMNS: list[tuple[str, str, str]] = [
    ("tasks", "sort_order", "INTEGER NOT NULL DEFAULT 0"),
    ("tasks", "nav_title", "TEXT"),
    ("tasks", "section", "TEXT"),
    ("tasks", "icon", "TEXT"),
    ("tasks", "gallery_picks", "INTEGER NOT NULL DEFAULT 1"),
    ("tasks", "input_image_labels", "TEXT NOT NULL DEFAULT '{}'"),
    ("tasks", "allow_text_only", "INTEGER NOT NULL DEFAULT 0"),
    ("generations", "seed", "INTEGER"),
    ("generations", "batch_id", "TEXT"),
    ("generations", "input_image_path", "TEXT"),
    ("generations", "hidden", "INTEGER NOT NULL DEFAULT 0"),
    ("vote_images", "hint", "TEXT NOT NULL DEFAULT ''"),
    ("vote_images", "pair", "TEXT NOT NULL DEFAULT ''"),
]


def init_db(db_path: Path) -> None:
    """Create tables (idempotent) and migrate older databases in place."""
    with get_connection(db_path) as conn:
        conn.execute(
            "PRAGMA journal_mode=WAL"
        )  # persistent; readers don't block writers
        # Migrate first so indexes in _SCHEMA can refer to new columns.
        _add_missing_columns(conn)
        conn.executescript(_SCHEMA)
        conn.execute(
            "INSERT OR IGNORE INTO app_settings (key, value, updated_at) "
            "VALUES (?, '1', ?)",
            (_API_ENABLED_KEY, now_utc()),
        )


def _add_missing_columns(conn: sqlite3.Connection) -> None:
    for table, column, ddl in _ADDED_COLUMNS:
        existing = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
        if not existing or column in existing:
            continue  # table not created yet, or already migrated
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")
        if (table, column) == ("tasks", "sort_order"):
            # Preserve the old creation order until the next JSON sync.
            conn.execute(
                """
                WITH ordered AS (
                    SELECT id, ROW_NUMBER() OVER (ORDER BY created_at) - 1 AS rn
                    FROM tasks
                )
                UPDATE tasks
                SET sort_order = (SELECT rn FROM ordered WHERE ordered.id = tasks.id)
                """
            )


# ── Tasks ────────────────────────────────────────────────────────────────────


def insert_or_update_task(db_path: Path, task: Task) -> None:
    """Upsert a task's definitional columns, preserving is_available."""
    with get_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO tasks (
                id, title, description, mode, nav_title, section, icon,
                target_image_path, input_image_paths, input_image_labels,
                allow_text_only, sort_order, gallery_picks,
                created_at, updated_at
            )
            VALUES (
                :id, :title, :description, :mode, :nav_title, :section, :icon,
                :target_image_path, :input_image_paths, :input_image_labels,
                :allow_text_only, :sort_order, :gallery_picks,
                :ts, :ts
            )
            ON CONFLICT(id) DO UPDATE SET
                title             = excluded.title,
                description       = excluded.description,
                mode              = excluded.mode,
                nav_title         = excluded.nav_title,
                section           = excluded.section,
                icon              = excluded.icon,
                target_image_path = excluded.target_image_path,
                input_image_paths = excluded.input_image_paths,
                input_image_labels = excluded.input_image_labels,
                allow_text_only   = excluded.allow_text_only,
                sort_order        = excluded.sort_order,
                gallery_picks     = excluded.gallery_picks,
                updated_at        = excluded.updated_at
            """,
            {
                **task.model_dump(
                    include={
                        "id",
                        "title",
                        "description",
                        "mode",
                        "nav_title",
                        "section",
                        "icon",
                        "target_image_path",
                        "sort_order",
                        "gallery_picks",
                    }
                ),
                "input_image_paths": json.dumps(task.input_image_paths),
                "input_image_labels": json.dumps(task.input_image_labels),
                "allow_text_only": int(task.allow_text_only),
                "ts": now_utc(),
            },
        )


def get_all_tasks(db_path: Path) -> list[Task]:
    with get_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM tasks ORDER BY sort_order, created_at"
        ).fetchall()
    return [Task.model_validate(dict(r)) for r in rows]


def get_available_tasks(db_path: Path) -> list[Task]:
    return [t for t in get_all_tasks(db_path) if t.is_available]


def get_task(db_path: Path, task_id: str) -> Task | None:
    with get_connection(db_path) as conn:
        row = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
    return Task.model_validate(dict(row)) if row else None


def set_task_availability(db_path: Path, task_id: str, is_available: bool) -> None:
    with get_connection(db_path) as conn:
        cur = conn.execute(
            "UPDATE tasks SET is_available=?, updated_at=? WHERE id=?",
            (int(is_available), now_utc(), task_id),
        )
        if cur.rowcount == 0:
            raise ValueError(f"Unknown task id: {task_id!r}")


# ── Generations ──────────────────────────────────────────────────────────────


class BudgetReachedError(Exception):
    """A user has used all of their generation budget for this task."""


def create_generation(
    db_path: Path,
    task_id: str,
    user_name: str,
    prompt: str,
    generation_budget: int,
    model_slug: str | None = None,
    seed: int | None = None,
    batch_id: str | None = None,
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
        live = conn.execute(
            """
            SELECT COUNT(*) FROM generations
            WHERE task_id=? AND LOWER(user_name)=LOWER(?) AND status<>'failed'
            """,
            (task_id, normalized),
        ).fetchone()[0]
        if live >= generation_budget:
            raise BudgetReachedError(
                f"'{normalized}' has used all {generation_budget} generations "
                "for this task."
            )
        conn.execute(
            """
            INSERT INTO generations
                (id, task_id, user_name, prompt, status, model_slug, seed,
                 batch_id, in_gallery, created_at, updated_at)
            VALUES (?, ?, ?, ?, 'pending', ?, ?, ?, 0, ?, ?)
            """,
            (gen_id, task_id, normalized, prompt, model_slug, seed, batch_id, ts, ts),
        )
    return gen_id


def set_generation_prediction(
    db_path: Path, generation_id: str, prediction_id: str
) -> None:
    with get_connection(db_path) as conn:
        conn.execute(
            "UPDATE generations SET prediction_id=?, updated_at=? WHERE id=?",
            (prediction_id, now_utc(), generation_id),
        )


def set_generation_input_image(db_path: Path, generation_id: str, path: str) -> None:
    """Remember which source image a generation edited (for before/after views)."""
    with get_connection(db_path) as conn:
        conn.execute(
            "UPDATE generations SET input_image_path=?, updated_at=? WHERE id=?",
            (path, now_utc(), generation_id),
        )


def update_generation_status(
    db_path: Path,
    generation_id: str,
    status: str,
    image_path: str | None = None,
    error_message: str | None = None,
) -> None:
    if status not in GENERATION_STATUSES:
        raise ValueError(
            f"Invalid status {status!r}. Must be one of: {sorted(GENERATION_STATUSES)}"
        )
    with get_connection(db_path) as conn:
        conn.execute(
            """
            UPDATE generations
            SET status=?, image_path=?, error_message=?, updated_at=?
            WHERE id=?
            """,
            (status, image_path, error_message, now_utc(), generation_id),
        )


def get_generation(db_path: Path, generation_id: str) -> Generation | None:
    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM generations WHERE id=?", (generation_id,)
        ).fetchone()
    return Generation.model_validate(dict(row)) if row else None


def submit_to_gallery(db_path: Path, generation_id: str, max_entries: int = 1) -> None:
    """Share a completed generation in the task gallery.

    A user may have up to `max_entries` shared generations per task (the task's
    `gallery_picks`). Sharing one more un-shares the user's oldest shared pick,
    so with the default of 1 the new image simply replaces the old one. Sibling
    generations are never deleted. Raises ValueError if the row is missing, not
    completed, or hidden by the admin.
    """
    if max_entries < 1:
        raise ValueError("max_entries must be >= 1")
    ts = now_utc()
    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT task_id, user_name, status, hidden, in_gallery "
            "FROM generations WHERE id=?",
            (generation_id,),
        ).fetchone()
        if not row:
            raise ValueError(f"Unknown generation id: {generation_id!r}")
        if row["hidden"]:
            raise ValueError(
                "This image was hidden from the gallery by the instructor."
            )
        if row["status"] != "completed":
            raise ValueError(
                f"Generation {generation_id!r} has status {row['status']!r}; "
                "only completed generations can be shown in the gallery."
            )
        if row["in_gallery"]:
            return
        shared = [
            r["id"]
            for r in conn.execute(
                """
                SELECT id FROM generations
                WHERE task_id=? AND LOWER(user_name)=LOWER(?) AND in_gallery=1
                ORDER BY updated_at, created_at
                """,
                (row["task_id"], row["user_name"]),
            )
        ]
        overflow = shared[: max(0, len(shared) - max_entries + 1)]
        conn.executemany(
            "UPDATE generations SET in_gallery=0, updated_at=? WHERE id=?",
            [(ts, gid) for gid in overflow],
        )
        conn.execute(
            "UPDATE generations SET in_gallery=1, updated_at=? WHERE id=?",
            (ts, generation_id),
        )


def remove_from_gallery(db_path: Path, generation_id: str) -> None:
    with get_connection(db_path) as conn:
        conn.execute(
            "UPDATE generations SET in_gallery=0, updated_at=? WHERE id=?",
            (now_utc(), generation_id),
        )


def hide_from_gallery(db_path: Path, generation_id: str) -> None:
    """Admin moderation: pull an entry from the gallery and block re-sharing it.

    The generation itself is kept (it still counts against the student's
    budget), but `submit_to_gallery` refuses it from now on.
    """
    with get_connection(db_path) as conn:
        conn.execute(
            "UPDATE generations SET in_gallery=0, hidden=1, updated_at=? WHERE id=?",
            (now_utc(), generation_id),
        )


def get_gallery_generations(db_path: Path, task_id: str) -> list[Generation]:
    """Return the gallery entries for a task — one per user that has chosen."""
    with get_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM generations WHERE task_id=? AND in_gallery=1 "
            "ORDER BY created_at",
            (task_id,),
        ).fetchall()
    return [Generation.model_validate(dict(r)) for r in rows]


def get_user_generations(
    db_path: Path, task_id: str, user_name: str
) -> list[Generation]:
    """Return all generations for a single user on a task, oldest first."""
    with get_connection(db_path) as conn:
        rows = conn.execute(
            """
            SELECT * FROM generations
            WHERE task_id=? AND LOWER(user_name)=LOWER(?)
            ORDER BY created_at
            """,
            (task_id, user_name.strip()),
        ).fetchall()
    return [Generation.model_validate(dict(r)) for r in rows]


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
    """Delete every generation (and its reactions) for one task."""
    with get_connection(db_path) as conn:
        conn.execute("DELETE FROM generations WHERE task_id=?", (task_id,))


def reset_all_generations(db_path: Path) -> None:
    """Delete every generation (and reaction) across all tasks."""
    with get_connection(db_path) as conn:
        conn.execute("DELETE FROM generations")


def delete_database(db_path: Path) -> None:
    """Remove the SQLite DB file and its WAL/SHM sidecars.

    Callers are expected to re-run init_db / sync_tasks_from_json afterwards
    so the schema and tasks are restored on the next render.
    """
    for suffix in ("", "-wal", "-shm"):
        path = db_path.with_name(db_path.name + suffix)
        if path.exists():
            path.unlink()


# ── Reactions (gallery likes) ────────────────────────────────────────────────


def toggle_reaction(db_path: Path, generation_id: str, user_name: str) -> bool:
    """Like or un-like a gallery entry. Returns True if the user now likes it.

    Users cannot like their own generation (raises ValueError).
    """
    normalized = user_name.strip()
    if not normalized:
        raise ValueError("user_name must not be empty")
    with get_connection(db_path) as conn:
        owner = conn.execute(
            "SELECT user_name FROM generations WHERE id=?", (generation_id,)
        ).fetchone()
        if not owner:
            raise ValueError(f"Unknown generation id: {generation_id!r}")
        if owner["user_name"].lower() == normalized.lower():
            raise ValueError("You can't like your own image.")
        deleted = conn.execute(
            "DELETE FROM reactions WHERE generation_id=? AND LOWER(user_name)=LOWER(?)",
            (generation_id, normalized),
        ).rowcount
        if deleted:
            return False
        conn.execute(
            "INSERT INTO reactions (generation_id, user_name, created_at) "
            "VALUES (?, ?, ?)",
            (generation_id, normalized, now_utc()),
        )
        return True


def get_reaction_counts(db_path: Path, task_id: str) -> dict[str, int]:
    """Return {generation_id: like_count} for the task's generations with likes."""
    with get_connection(db_path) as conn:
        rows = conn.execute(
            """
            SELECT r.generation_id, COUNT(*) AS n
            FROM reactions r JOIN generations g ON g.id = r.generation_id
            WHERE g.task_id=?
            GROUP BY r.generation_id
            """,
            (task_id,),
        ).fetchall()
    return {r["generation_id"]: r["n"] for r in rows}


def get_user_reactions(db_path: Path, task_id: str, user_name: str) -> set[str]:
    """Return the ids of generations on this task the user has liked."""
    with get_connection(db_path) as conn:
        rows = conn.execute(
            """
            SELECT r.generation_id
            FROM reactions r JOIN generations g ON g.id = r.generation_id
            WHERE g.task_id=? AND LOWER(r.user_name)=LOWER(?)
            """,
            (task_id, user_name.strip()),
        ).fetchall()
    return {r["generation_id"] for r in rows}


# ── Vote images / Votes ──────────────────────────────────────────────────────


def upsert_vote_image(db_path: Path, image: VoteImage) -> None:
    """Insert or update one vote image's definitional columns."""
    if image.label not in VOTE_LABELS:
        raise ValueError(
            f"Invalid label {image.label!r}. Must be one of: {sorted(VOTE_LABELS)}"
        )
    with get_connection(db_path) as conn:
        _upsert_vote_image(conn, image)


def _upsert_vote_image(conn: sqlite3.Connection, image: VoteImage) -> None:
    conn.execute(
        """
        INSERT INTO vote_images
            (id, task_id, image_path, label, hint, pair, sort_order,
             created_at, updated_at)
        VALUES (:id, :task_id, :image_path, :label, :hint, :pair, :sort_order,
                :ts, :ts)
        ON CONFLICT(task_id, id) DO UPDATE SET
            image_path = excluded.image_path,
            label      = excluded.label,
            hint       = excluded.hint,
            pair       = excluded.pair,
            sort_order = excluded.sort_order,
            updated_at = excluded.updated_at
        """,
        {
            **image.model_dump(
                include={
                    "id",
                    "task_id",
                    "image_path",
                    "label",
                    "hint",
                    "pair",
                    "sort_order",
                }
            ),
            "ts": now_utc(),
        },
    )


def sync_vote_images(db_path: Path, task_id: str, images: list[VoteImage]) -> None:
    """Replace a task's vote images with `images`, deleting any that vanished.

    Runs in one transaction. Votes referencing a removed image are cascaded
    away. Re-syncing the same images preserves their votes (rows are upserted,
    not recreated).
    """
    keep_ids = [img.id for img in images]
    placeholders = ",".join("?" for _ in keep_ids)
    with get_connection(db_path) as conn:
        if keep_ids:
            conn.execute(
                f"DELETE FROM vote_images WHERE task_id=? AND id NOT IN ({placeholders})",
                (task_id, *keep_ids),
            )
        else:
            conn.execute("DELETE FROM vote_images WHERE task_id=?", (task_id,))
        for img in images:
            _upsert_vote_image(conn, img.model_copy(update={"task_id": task_id}))


def get_vote_images(db_path: Path, task_id: str) -> list[VoteImage]:
    with get_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM vote_images WHERE task_id=? ORDER BY sort_order, created_at",
            (task_id,),
        ).fetchall()
    return [VoteImage.model_validate(dict(r)) for r in rows]


def cast_vote(
    db_path: Path, task_id: str, image_id: str, user_name: str, vote: str
) -> None:
    """Record (or change) one user's vote for one image.

    One row per (image, user); re-voting updates the existing row. Raises
    ValueError on blank user, invalid label, or unknown image.
    """
    normalized = user_name.strip()
    if not normalized:
        raise ValueError("user_name must not be empty")
    if vote not in VOTE_LABELS:
        raise ValueError(
            f"Invalid vote {vote!r}. Must be one of: {sorted(VOTE_LABELS)}"
        )
    ts = now_utc()
    with get_connection(db_path) as conn:
        img = conn.execute(
            "SELECT 1 FROM vote_images WHERE id=? AND task_id=?", (image_id, task_id)
        ).fetchone()
        if not img:
            raise ValueError(f"Unknown vote image {image_id!r} for task {task_id!r}")
        conn.execute(
            """
            INSERT INTO votes
                (id, task_id, image_id, user_name, vote, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (task_id, image_id, LOWER(user_name)) DO UPDATE SET
                vote = excluded.vote, updated_at = excluded.updated_at
            """,
            (new_id(), task_id, image_id, normalized, vote, ts, ts),
        )


def get_user_votes(db_path: Path, task_id: str, user_name: str) -> dict[str, str]:
    """Return {image_id: vote} for one user on one task."""
    with get_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT image_id, vote FROM votes "
            "WHERE task_id=? AND LOWER(user_name)=LOWER(?)",
            (task_id, user_name.strip()),
        ).fetchall()
    return {r["image_id"]: r["vote"] for r in rows}


def get_vote_tallies(db_path: Path, task_id: str) -> dict[str, dict[str, int]]:
    """Return {image_id: {"real": n, "synthetic": m}} for every image on a task."""
    with get_connection(db_path) as conn:
        image_ids = [
            r["id"]
            for r in conn.execute(
                "SELECT id FROM vote_images WHERE task_id=?", (task_id,)
            )
        ]
        rows = conn.execute(
            "SELECT image_id, vote, COUNT(*) AS n FROM votes "
            "WHERE task_id=? GROUP BY image_id, vote",
            (task_id,),
        ).fetchall()
    tallies = {i: {"real": 0, "synthetic": 0} for i in image_ids}
    for r in rows:
        bucket = tallies.setdefault(r["image_id"], {"real": 0, "synthetic": 0})
        if r["vote"] in bucket:
            bucket[r["vote"]] = r["n"]
    return tallies


@dataclass(frozen=True)
class VoteScore:
    user_name: str
    correct: int
    voted: int


def get_vote_scores(db_path: Path, task_id: str) -> list[VoteScore]:
    """Per-user score on a vote task, best first (ties: more votes, then name)."""
    with get_connection(db_path) as conn:
        rows = conn.execute(
            """
            SELECT MIN(v.user_name) AS user_name,
                   SUM(v.vote = i.label) AS correct,
                   COUNT(*) AS voted
            FROM votes v
            JOIN vote_images i ON i.task_id = v.task_id AND i.id = v.image_id
            WHERE v.task_id=?
            GROUP BY LOWER(v.user_name)
            ORDER BY correct DESC, voted DESC, LOWER(MIN(v.user_name))
            """,
            (task_id,),
        ).fetchall()
    return [VoteScore(r["user_name"], r["correct"], r["voted"]) for r in rows]


def reset_task_votes(db_path: Path, task_id: str) -> None:
    """Delete every vote for one task (keeps the vote images)."""
    with get_connection(db_path) as conn:
        conn.execute("DELETE FROM votes WHERE task_id=?", (task_id,))


def reset_all_votes(db_path: Path) -> None:
    """Delete every vote across all tasks."""
    with get_connection(db_path) as conn:
        conn.execute("DELETE FROM votes")


# ── Class statistics (admin) ─────────────────────────────────────────────────


@dataclass(frozen=True)
class ClassStats:
    participants: int
    generations: int
    completed: int
    failed: int
    pending: int
    avg_seconds: float | None


def get_class_stats(db_path: Path) -> ClassStats:
    """Headline numbers for the admin page (across all tasks)."""
    with get_connection(db_path) as conn:
        participants = conn.execute(
            """
            SELECT COUNT(*) FROM (
                SELECT LOWER(user_name) FROM generations
                UNION SELECT LOWER(user_name) FROM votes
            )
            """
        ).fetchone()[0]
        counts = {
            r["status"]: r["n"]
            for r in conn.execute(
                "SELECT status, COUNT(*) AS n FROM generations GROUP BY status"
            )
        }
        done = conn.execute(
            "SELECT created_at, updated_at FROM generations WHERE status='completed'"
        ).fetchall()
    durations = [
        (end - start).total_seconds()
        for r in done
        if (start := parse_utc(r["created_at"])) and (end := parse_utc(r["updated_at"]))
    ]
    return ClassStats(
        participants=participants,
        generations=sum(counts.values()),
        completed=counts.get("completed", 0),
        failed=counts.get("failed", 0),
        pending=counts.get("pending", 0),
        avg_seconds=sum(durations) / len(durations) if durations else None,
    )


# ── App settings ─────────────────────────────────────────────────────────────


def get_setting(db_path: Path, key: str) -> str | None:
    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT value FROM app_settings WHERE key=?", (key,)
        ).fetchone()
    return row["value"] if row else None


def set_setting(db_path: Path, key: str, value: str) -> None:
    with get_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO app_settings (key, value, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                value      = excluded.value,
                updated_at = excluded.updated_at
            """,
            (key, value, now_utc()),
        )


def is_api_enabled(db_path: Path) -> bool:
    return get_setting(db_path, _API_ENABLED_KEY) == "1"


def set_api_enabled(db_path: Path, enabled: bool) -> None:
    set_setting(db_path, _API_ENABLED_KEY, "1" if enabled else "0")


def is_vote_revealed(db_path: Path, task_id: str) -> bool:
    """Whether the admin has revealed the true labels of a vote task."""
    return get_setting(db_path, _REVEAL_KEY_PREFIX + task_id) == "1"


def set_vote_revealed(db_path: Path, task_id: str, revealed: bool) -> None:
    set_setting(db_path, _REVEAL_KEY_PREFIX + task_id, "1" if revealed else "0")


def get_budget_override(db_path: Path) -> int | None:
    """Per-task generation budget set by the admin, or None (use the env default)."""
    value = get_setting(db_path, _BUDGET_KEY)
    return int(value) if value else None


def set_budget_override(db_path: Path, budget: int | None) -> None:
    """Set the admin's budget override; None goes back to the env default."""
    if budget is not None and budget < 1:
        raise ValueError("generation budget must be >= 1")
    set_setting(db_path, _BUDGET_KEY, "" if budget is None else str(budget))
