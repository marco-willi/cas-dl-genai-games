"""Tests for the merged submissions table — drafts + choose-one flow."""

import pytest

from genai_cv_game.db import (
    DuplicateSubmissionError,
    MaxAttemptsReachedError,
    choose_submission,
    create_submission,
    delete_submission,
    delete_team_submissions,
    get_submissions_for_round,
    get_team_submissions,
    init_db,
    insert_or_update_round,
    reset_round_submissions,
    update_round_state,
    update_submission_status,
)
from genai_cv_game.models import Round


def _round(rid="r1") -> Round:
    return Round(id=rid, title=f"R {rid}", description="d", mode="business")


def _setup(tmp_path):
    db = tmp_path / "app.db"
    init_db(db)
    insert_or_update_round(db, _round("r1"))
    return db


def test_create_submission_returns_id_and_pending_draft(tmp_path):
    db = _setup(tmp_path)
    sid = create_submission(db, "r1", "Team A", "p", max_attempts=3)
    drafts = get_team_submissions(db, "r1", "Team A")
    assert len(drafts) == 1
    assert drafts[0].id == sid
    assert drafts[0].status == "pending"
    assert drafts[0].is_chosen is False
    assert drafts[0].image_path is None
    assert drafts[0].prediction_id is None


def test_create_submission_blocks_when_max_reached(tmp_path):
    db = _setup(tmp_path)
    create_submission(db, "r1", "Team A", "p1", max_attempts=2)
    create_submission(db, "r1", "Team A", "p2", max_attempts=2)
    with pytest.raises(MaxAttemptsReachedError, match="limit of 2"):
        create_submission(db, "r1", "Team A", "p3", max_attempts=2)


def test_create_submission_case_insensitive_in_count(tmp_path):
    db = _setup(tmp_path)
    create_submission(db, "r1", "Team A", "p1", max_attempts=1)
    with pytest.raises(MaxAttemptsReachedError):
        create_submission(db, "r1", "team a", "p2", max_attempts=1)


def test_create_submission_strips_team_name(tmp_path):
    db = _setup(tmp_path)
    create_submission(db, "r1", "  Team A  ", "p1", max_attempts=2)
    drafts = get_team_submissions(db, "r1", "Team A")
    assert len(drafts) == 1
    assert drafts[0].team_name == "Team A"


def test_create_submission_rejects_empty_team(tmp_path):
    db = _setup(tmp_path)
    with pytest.raises(ValueError):
        create_submission(db, "r1", "  ", "p", max_attempts=3)


def test_create_submission_rejects_zero_max(tmp_path):
    db = _setup(tmp_path)
    with pytest.raises(ValueError):
        create_submission(db, "r1", "Team A", "p", max_attempts=0)


def test_delete_submission(tmp_path):
    db = _setup(tmp_path)
    s1 = create_submission(db, "r1", "Team A", "p1", max_attempts=3)
    s2 = create_submission(db, "r1", "Team A", "p2", max_attempts=3)
    delete_submission(db, s1)
    rows = get_team_submissions(db, "r1", "Team A")
    assert [r.id for r in rows] == [s2]


def test_delete_team_submissions(tmp_path):
    db = _setup(tmp_path)
    create_submission(db, "r1", "Team A", "p1", max_attempts=3)
    create_submission(db, "r1", "Team A", "p2", max_attempts=3)
    create_submission(db, "r1", "Team B", "px", max_attempts=3)
    delete_team_submissions(db, "r1", "Team A")
    assert get_team_submissions(db, "r1", "Team A") == []
    assert len(get_team_submissions(db, "r1", "Team B")) == 1


def test_choose_marks_one_row_and_drops_siblings(tmp_path):
    db = _setup(tmp_path)
    s1 = create_submission(db, "r1", "Team A", "p1", max_attempts=3)
    s2 = create_submission(db, "r1", "Team A", "p2", max_attempts=3)
    update_submission_status(db, s1, "completed", image_path="generated/s1.png")
    update_submission_status(db, s2, "completed", image_path="generated/s2.png")

    choose_submission(db, s2)

    rows = get_team_submissions(db, "r1", "Team A")
    assert len(rows) == 1
    assert rows[0].id == s2
    assert rows[0].is_chosen is True


def test_choose_rejects_non_completed(tmp_path):
    db = _setup(tmp_path)
    sid = create_submission(db, "r1", "Team A", "p1", max_attempts=3)
    with pytest.raises(ValueError, match="completed submissions"):
        choose_submission(db, sid)


def test_choose_rejects_unknown(tmp_path):
    db = _setup(tmp_path)
    with pytest.raises(ValueError, match="Unknown submission id"):
        choose_submission(db, "nope")


def test_create_submission_blocked_after_team_already_chose(tmp_path):
    db = _setup(tmp_path)
    sid = create_submission(db, "r1", "Team A", "p", max_attempts=3)
    update_submission_status(db, sid, "completed", image_path="x.png")
    choose_submission(db, sid)

    with pytest.raises(DuplicateSubmissionError):
        create_submission(db, "r1", "Team A", "again", max_attempts=3)


def test_choose_independent_across_teams(tmp_path):
    """One team's choice does not consume another team's attempt budget."""
    db = _setup(tmp_path)
    sa = create_submission(db, "r1", "Team A", "p", max_attempts=1)
    update_submission_status(db, sa, "completed", image_path="x.png")
    choose_submission(db, sa)
    # Team B still gets its own attempt
    create_submission(db, "r1", "Team B", "p", max_attempts=1)


def test_get_submissions_for_round_returns_chosen_only(tmp_path):
    db = _setup(tmp_path)
    a = create_submission(db, "r1", "Team A", "p", max_attempts=3)
    create_submission(db, "r1", "Team B", "p", max_attempts=3)  # draft only
    update_submission_status(db, a, "completed", image_path="x.png")
    choose_submission(db, a)

    rows = get_submissions_for_round(db, "r1")
    assert [r.id for r in rows] == [a]


def test_reset_round_wipes_all_rows(tmp_path):
    db = _setup(tmp_path)
    create_submission(db, "r1", "Team A", "p", max_attempts=3)
    update_round_state(db, "r1", submissions_open=True)
    reset_round_submissions(db, "r1")
    assert get_team_submissions(db, "r1", "Team A") == []
