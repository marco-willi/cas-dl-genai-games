import sqlite3

import pytest

from genai_cv_game.db import (
    choose_submission,
    create_submission,
    create_vote,
    delete_submission,
    get_active_round,
    get_all_rounds,
    get_submissions_for_round,
    get_team_submissions,
    get_vote_counts,
    init_db,
    insert_or_update_round,
    reset_round_submissions,
    set_active_round,
    update_round_state,
    update_submission_status,
)
from genai_cv_game.models import Round


def _round(id="r1", mode="business", **kwargs) -> Round:
    return Round(
        id=id,
        title=f"Round {id}",
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
    assert {"rounds", "submissions", "votes"} <= tables
    assert "attempts" not in tables
    assert conn.execute("SELECT COUNT(*) FROM rounds").fetchone()[0] == 0


def test_insert_and_get_round(tmp_path):
    db = tmp_path / "app.db"
    init_db(db)
    insert_or_update_round(db, _round("r1", mode="match"))
    rounds = get_all_rounds(db)
    assert len(rounds) == 1
    assert rounds[0].id == "r1"
    assert rounds[0].mode == "match"
    assert rounds[0].created_at != ""


def test_round_input_image_paths_roundtrip(tmp_path):
    db = tmp_path / "app.db"
    init_db(db)
    insert_or_update_round(
        db,
        _round(
            "edit1",
            mode="edit",
            input_image_paths=["assets/input_images/edit/edit1.jpg"],
        ),
    )
    [r] = get_all_rounds(db)
    assert r.mode == "edit"
    assert r.input_image_paths == ["assets/input_images/edit/edit1.jpg"]


def test_round_input_image_paths_default_empty(tmp_path):
    db = tmp_path / "app.db"
    init_db(db)
    insert_or_update_round(db, _round("b1", mode="business"))
    [r] = get_all_rounds(db)
    assert r.input_image_paths == []


def test_upsert_round_preserves_state(tmp_path):
    db = tmp_path / "app.db"
    init_db(db)
    insert_or_update_round(db, _round("r1"))
    set_active_round(db, "r1")
    update_round_state(db, "r1", submissions_open=True)

    insert_or_update_round(
        db, Round(id="r1", title="New Title", description="desc", mode="business")
    )
    rounds = get_all_rounds(db)
    assert rounds[0].title == "New Title"
    assert rounds[0].is_active is True
    assert rounds[0].submissions_open is True


def test_set_active_round_exclusive(tmp_path):
    db = tmp_path / "app.db"
    init_db(db)
    insert_or_update_round(db, _round("r1"))
    insert_or_update_round(db, _round("r2"))

    set_active_round(db, "r1")
    assert get_active_round(db).id == "r1"

    set_active_round(db, "r2")
    active = get_active_round(db)
    assert active.id == "r2"
    all_rounds = get_all_rounds(db)
    assert sum(1 for r in all_rounds if r.is_active) == 1


def test_update_round_state(tmp_path):
    db = tmp_path / "app.db"
    init_db(db)
    insert_or_update_round(db, _round("r1"))
    update_round_state(db, "r1", gallery_revealed=True, prompts_revealed=True)
    r = get_all_rounds(db)[0]
    assert r.gallery_revealed is True
    assert r.prompts_revealed is True
    assert r.submissions_open is False


def test_update_round_state_rejects_unknown_key(tmp_path):
    db = tmp_path / "app.db"
    init_db(db)
    insert_or_update_round(db, _round("r1"))
    with pytest.raises(ValueError):
        update_round_state(db, "r1", nonexistent_flag=True)


def test_create_and_get_draft(tmp_path):
    db = tmp_path / "app.db"
    init_db(db)
    insert_or_update_round(db, _round("r1"))
    sub_id = create_submission(db, "r1", "Team A", "a red car", max_attempts=3)
    drafts = get_team_submissions(db, "r1", "Team A")
    assert len(drafts) == 1
    assert drafts[0].id == sub_id
    assert drafts[0].status == "pending"
    assert drafts[0].team_name == "Team A"
    assert drafts[0].image_path is None
    assert drafts[0].is_chosen is False


def test_update_submission_status(tmp_path):
    db = tmp_path / "app.db"
    init_db(db)
    insert_or_update_round(db, _round("r1"))
    sub_id = create_submission(db, "r1", "Team B", "blue sky", max_attempts=3)
    update_submission_status(db, sub_id, "completed", image_path="generated/r1/img.png")
    drafts = get_team_submissions(db, "r1", "Team B")
    assert drafts[0].status == "completed"
    assert drafts[0].image_path == "generated/r1/img.png"
    assert drafts[0].error_message is None


def test_reset_round_submissions(tmp_path):
    db = tmp_path / "app.db"
    init_db(db)
    insert_or_update_round(db, _round("r1"))
    sub_id = create_submission(db, "r1", "Team C", "forest", max_attempts=3)
    update_submission_status(db, sub_id, "completed", image_path="x.png")
    choose_submission(db, sub_id)
    create_vote(db, "r1", sub_id, "voter1")

    reset_round_submissions(db, "r1")
    assert get_submissions_for_round(db, "r1") == []
    assert get_vote_counts(db, "r1") == {}


def test_vote_uniqueness(tmp_path):
    db = tmp_path / "app.db"
    init_db(db)
    insert_or_update_round(db, _round("r1"))
    sub_id = create_submission(db, "r1", "Team D", "night sky", max_attempts=3)
    create_vote(db, "r1", sub_id, "voter1")
    with pytest.raises(sqlite3.IntegrityError):
        create_vote(db, "r1", sub_id, "voter1")


def test_create_submission_rejects_empty_team_name(tmp_path):
    db = tmp_path / "app.db"
    init_db(db)
    insert_or_update_round(db, _round("r1"))
    with pytest.raises(ValueError):
        create_submission(db, "r1", "   ", "prompt", max_attempts=3)


def test_same_team_can_submit_in_different_rounds(tmp_path):
    db = tmp_path / "app.db"
    init_db(db)
    insert_or_update_round(db, _round("r1"))
    insert_or_update_round(db, _round("r2"))
    create_submission(db, "r1", "Team A", "first", max_attempts=3)
    sub2 = create_submission(db, "r2", "Team A", "second", max_attempts=3)
    assert sub2 is not None


def test_delete_submission_clears_row_and_votes(tmp_path):
    db = tmp_path / "app.db"
    init_db(db)
    insert_or_update_round(db, _round("r1"))
    sub_id = create_submission(db, "r1", "Team X", "p", max_attempts=3)
    update_submission_status(db, sub_id, "completed", image_path="x.png")
    choose_submission(db, sub_id)
    create_vote(db, "r1", sub_id, "voter1")
    delete_submission(db, sub_id)
    assert get_submissions_for_round(db, "r1") == []
    assert get_vote_counts(db, "r1") == {}


def test_reset_round_clears_state_flags(tmp_path):
    db = tmp_path / "app.db"
    init_db(db)
    insert_or_update_round(db, _round("r1"))
    update_round_state(
        db,
        "r1",
        submissions_open=True,
        gallery_revealed=True,
        prompts_revealed=True,
        voting_open=True,
    )
    reset_round_submissions(db, "r1")
    r = get_all_rounds(db)[0]
    assert r.submissions_open is False
    assert r.gallery_revealed is False
    assert r.prompts_revealed is False
    assert r.voting_open is False


def test_update_submission_status_rejects_invalid_status(tmp_path):
    db = tmp_path / "app.db"
    init_db(db)
    insert_or_update_round(db, _round("r1"))
    sub_id = create_submission(db, "r1", "Team A", "p", max_attempts=3)
    with pytest.raises(ValueError, match="Invalid status"):
        update_submission_status(db, sub_id, "in_progress")


def test_set_active_round_rejects_unknown_id(tmp_path):
    db = tmp_path / "app.db"
    init_db(db)
    insert_or_update_round(db, _round("r1"))
    with pytest.raises(ValueError, match="Unknown round id"):
        set_active_round(db, "does_not_exist")


def test_vote_normalization_blocks_casing_dupes(tmp_path):
    db = tmp_path / "app.db"
    init_db(db)
    insert_or_update_round(db, _round("r1"))
    sub_id = create_submission(db, "r1", "Team A", "p", max_attempts=3)
    create_vote(db, "r1", sub_id, "Alice")
    with pytest.raises(sqlite3.IntegrityError):
        create_vote(db, "r1", sub_id, "alice")
    with pytest.raises(sqlite3.IntegrityError):
        create_vote(db, "r1", sub_id, "  ALICE  ")


def test_get_vote_counts(tmp_path):
    db = tmp_path / "app.db"
    init_db(db)
    insert_or_update_round(db, _round("r1"))
    s1 = create_submission(db, "r1", "Team E", "prompt1", max_attempts=3)
    s2 = create_submission(db, "r1", "Team F", "prompt2", max_attempts=3)
    create_vote(db, "r1", s1, "voter1")
    create_vote(db, "r1", s1, "voter2")
    create_vote(db, "r1", s2, "voter3")
    counts = get_vote_counts(db, "r1")
    assert counts[s1] == 2
    assert counts[s2] == 1
