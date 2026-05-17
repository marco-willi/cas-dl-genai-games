from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Generator

from genai_cv_game.models import Round, Submission, Vote
from genai_cv_game.utils import new_id, now_utc

_ALLOWED_ROUND_STATE_KEYS = frozenset(
    {"submissions_open", "gallery_revealed", "prompts_revealed", "voting_open"}
)
_ALLOWED_SUBMISSION_STATUSES = frozenset({"pending", "completed", "failed"})


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
    _migrate_schema(db_path)


def _migrate_schema(db_path: Path) -> None:
    """Idempotent additive migrations for DBs created by older versions."""
    with get_connection(db_path) as conn:
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(submissions)")}
        if "prediction_id" not in cols:
            conn.execute("ALTER TABLE submissions ADD COLUMN prediction_id TEXT")


def create_tables(db_path: Path) -> None:
    with get_connection(db_path) as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS rounds (
                id                TEXT PRIMARY KEY,
                title             TEXT NOT NULL,
                description       TEXT NOT NULL,
                mode              TEXT NOT NULL,
                target_image_path TEXT,
                is_active         INTEGER NOT NULL DEFAULT 0,
                submissions_open  INTEGER NOT NULL DEFAULT 0,
                gallery_revealed  INTEGER NOT NULL DEFAULT 0,
                prompts_revealed  INTEGER NOT NULL DEFAULT 0,
                voting_open       INTEGER NOT NULL DEFAULT 0,
                created_at        TEXT NOT NULL,
                updated_at        TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS submissions (
                id            TEXT PRIMARY KEY,
                round_id      TEXT NOT NULL REFERENCES rounds(id) ON DELETE CASCADE,
                team_name     TEXT NOT NULL,
                prompt        TEXT NOT NULL,
                image_path    TEXT,
                status        TEXT NOT NULL,
                error_message TEXT,
                prediction_id TEXT,
                created_at    TEXT NOT NULL,
                updated_at    TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS votes (
                id            TEXT PRIMARY KEY,
                round_id      TEXT NOT NULL REFERENCES rounds(id) ON DELETE CASCADE,
                submission_id TEXT NOT NULL REFERENCES submissions(id) ON DELETE CASCADE,
                voter_name    TEXT NOT NULL,
                created_at    TEXT NOT NULL,
                UNIQUE (round_id, voter_name)
            );

            CREATE UNIQUE INDEX IF NOT EXISTS idx_submissions_round_team
                ON submissions (round_id, LOWER(team_name));
        """)


def insert_or_update_round(db_path: Path, round: Round) -> None:
    ts = now_utc()
    with get_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO rounds (id, title, description, mode, target_image_path, created_at, updated_at)
            VALUES (:id, :title, :description, :mode, :target_image_path, :ts, :ts)
            ON CONFLICT(id) DO UPDATE SET
                title             = excluded.title,
                description       = excluded.description,
                mode              = excluded.mode,
                target_image_path = excluded.target_image_path,
                updated_at        = excluded.updated_at
            """,
            {
                "id": round.id,
                "title": round.title,
                "description": round.description,
                "mode": round.mode,
                "target_image_path": round.target_image_path,
                "ts": ts,
            },
        )


def get_all_rounds(db_path: Path) -> list[Round]:
    with get_connection(db_path) as conn:
        rows = conn.execute("SELECT * FROM rounds ORDER BY created_at").fetchall()
    return [_row_to_round(r) for r in rows]


def get_active_round(db_path: Path) -> Round | None:
    with get_connection(db_path) as conn:
        row = conn.execute("SELECT * FROM rounds WHERE is_active=1 LIMIT 1").fetchone()
    return _row_to_round(row) if row else None


def set_active_round(db_path: Path, round_id: str) -> None:
    ts = now_utc()
    with get_connection(db_path) as conn:
        exists = conn.execute("SELECT 1 FROM rounds WHERE id=?", (round_id,)).fetchone()
        if not exists:
            raise ValueError(f"Unknown round id: {round_id!r}")
        conn.execute(
            "UPDATE rounds SET is_active=0, updated_at=? WHERE is_active=1", (ts,)
        )
        conn.execute(
            "UPDATE rounds SET is_active=1, updated_at=? WHERE id=?", (ts, round_id)
        )


def update_round_state(db_path: Path, round_id: str, **kwargs) -> None:
    unknown = set(kwargs) - _ALLOWED_ROUND_STATE_KEYS
    if unknown:
        raise ValueError(f"Unknown round state keys: {unknown}")
    if not kwargs:
        return
    ts = now_utc()
    set_clause = ", ".join(f"{k}=?" for k in kwargs)
    values = [int(v) for v in kwargs.values()] + [ts, round_id]
    with get_connection(db_path) as conn:
        conn.execute(f"UPDATE rounds SET {set_clause}, updated_at=? WHERE id=?", values)


class DuplicateSubmissionError(Exception):
    """A submission for (round_id, team_name) already exists."""


def create_submission(db_path: Path, round_id: str, team_name: str, prompt: str) -> str:
    sub_id = new_id()
    ts = now_utc()
    normalized = team_name.strip()
    if not normalized:
        raise ValueError("team_name must not be empty")
    try:
        with get_connection(db_path) as conn:
            conn.execute(
                """
                INSERT INTO submissions (id, round_id, team_name, prompt, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, 'pending', ?, ?)
                """,
                (sub_id, round_id, normalized, prompt, ts, ts),
            )
    except sqlite3.IntegrityError as e:
        raise DuplicateSubmissionError(
            f"Team '{normalized}' already has a submission for this round."
        ) from e
    return sub_id


def set_submission_prediction(
    db_path: Path, submission_id: str, prediction_id: str
) -> None:
    ts = now_utc()
    with get_connection(db_path) as conn:
        conn.execute(
            "UPDATE submissions SET prediction_id=?, updated_at=? WHERE id=?",
            (prediction_id, ts, submission_id),
        )


def update_submission_status(
    db_path: Path,
    submission_id: str,
    status: str,
    image_path: str | None = None,
    error_message: str | None = None,
) -> None:
    if status not in _ALLOWED_SUBMISSION_STATUSES:
        raise ValueError(
            f"Invalid status {status!r}. Must be one of: "
            f"{sorted(_ALLOWED_SUBMISSION_STATUSES)}"
        )
    ts = now_utc()
    with get_connection(db_path) as conn:
        conn.execute(
            """
            UPDATE submissions
            SET status=?, image_path=?, error_message=?, updated_at=?
            WHERE id=?
            """,
            (status, image_path, error_message, ts, submission_id),
        )


def get_submissions_for_round(db_path: Path, round_id: str) -> list[Submission]:
    with get_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM submissions WHERE round_id=? ORDER BY created_at",
            (round_id,),
        ).fetchall()
    return [_row_to_submission(r) for r in rows]


def delete_submission(db_path: Path, submission_id: str) -> None:
    with get_connection(db_path) as conn:
        conn.execute("DELETE FROM submissions WHERE id=?", (submission_id,))


def reset_round_submissions(db_path: Path, round_id: str) -> None:
    """Delete all submissions and votes for a round, and reset its state flags.

    State flags are reset so the gallery is not left visible (and voting is not
    left open) after a mid-class reset.
    """
    ts = now_utc()
    with get_connection(db_path) as conn:
        conn.execute("DELETE FROM votes WHERE round_id=?", (round_id,))
        conn.execute("DELETE FROM submissions WHERE round_id=?", (round_id,))
        conn.execute(
            """
            UPDATE rounds
            SET submissions_open=0,
                gallery_revealed=0,
                prompts_revealed=0,
                voting_open=0,
                updated_at=?
            WHERE id=?
            """,
            (ts, round_id),
        )


def create_vote(
    db_path: Path, round_id: str, submission_id: str, voter_name: str
) -> str:
    normalized = voter_name.strip().lower()
    if not normalized:
        raise ValueError("voter_name must not be empty")
    vote_id = new_id()
    ts = now_utc()
    with get_connection(db_path) as conn:
        conn.execute(
            "INSERT INTO votes (id, round_id, submission_id, voter_name, created_at) VALUES (?, ?, ?, ?, ?)",
            (vote_id, round_id, submission_id, normalized, ts),
        )
    return vote_id


def delete_database(db_path: Path) -> None:
    """Remove the SQLite DB file and its WAL/SHM sidecars.

    Callers are expected to re-run init_db / sync_rounds_from_json afterwards
    so the schema and rounds are restored on the next render.
    """
    for suffix in ("", "-wal", "-shm"):
        sidecar = db_path.with_name(db_path.name + suffix) if suffix else db_path
        if sidecar.exists():
            sidecar.unlink()


def get_vote_counts(db_path: Path, round_id: str) -> dict[str, int]:
    with get_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT submission_id, COUNT(*) as cnt FROM votes WHERE round_id=? GROUP BY submission_id",
            (round_id,),
        ).fetchall()
    return {row["submission_id"]: row["cnt"] for row in rows}


def _row_to_round(row: sqlite3.Row) -> Round:
    return Round(
        id=row["id"],
        title=row["title"],
        description=row["description"],
        mode=row["mode"],
        target_image_path=row["target_image_path"],
        is_active=bool(row["is_active"]),
        submissions_open=bool(row["submissions_open"]),
        gallery_revealed=bool(row["gallery_revealed"]),
        prompts_revealed=bool(row["prompts_revealed"]),
        voting_open=bool(row["voting_open"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _row_to_submission(row: sqlite3.Row) -> Submission:
    keys = row.keys()
    return Submission(
        id=row["id"],
        round_id=row["round_id"],
        team_name=row["team_name"],
        prompt=row["prompt"],
        image_path=row["image_path"],
        status=row["status"],
        error_message=row["error_message"],
        prediction_id=row["prediction_id"] if "prediction_id" in keys else None,
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _row_to_vote(row: sqlite3.Row) -> Vote:
    return Vote(
        id=row["id"],
        round_id=row["round_id"],
        submission_id=row["submission_id"],
        voter_name=row["voter_name"],
        created_at=row["created_at"],
    )
