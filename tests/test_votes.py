import pytest

from genai_cv_game.db import (
    cast_vote,
    get_user_votes,
    get_vote_images,
    get_vote_tallies,
    init_db,
    insert_or_update_task,
    reset_all_votes,
    reset_task_votes,
    sync_vote_images,
)
from genai_cv_game.models import Task, VoteImage


def _vote_task(db, task_id="v1", images=("img_01", "img_02")) -> Task:
    insert_or_update_task(
        db,
        Task(id=task_id, title="Vote", description="d", mode="vote"),
    )
    vote_images = [
        VoteImage(
            id=img,
            image_path=f"assets/vote_images/{task_id}/{img}.png",
            label="real" if i % 2 == 0 else "synthetic",
            sort_order=i,
        )
        for i, img in enumerate(images)
    ]
    sync_vote_images(db, task_id, vote_images)
    return Task(id=task_id, title="Vote", description="d", mode="vote")


def test_sync_and_get_vote_images(tmp_path):
    db = tmp_path / "app.db"
    init_db(db)
    _vote_task(db)
    images = get_vote_images(db, "v1")
    assert [i.id for i in images] == ["img_01", "img_02"]
    assert images[0].label == "real"
    assert images[0].task_id == "v1"


def test_cast_vote_records_choice(tmp_path):
    db = tmp_path / "app.db"
    init_db(db)
    _vote_task(db)
    cast_vote(db, "v1", "img_01", "Alice", "real")
    assert get_user_votes(db, "v1", "Alice") == {"img_01": "real"}


def test_recasting_updates_in_place(tmp_path):
    db = tmp_path / "app.db"
    init_db(db)
    _vote_task(db)
    cast_vote(db, "v1", "img_01", "Alice", "real")
    cast_vote(db, "v1", "img_01", "Alice", "synthetic")
    assert get_user_votes(db, "v1", "Alice") == {"img_01": "synthetic"}
    tally = get_vote_tallies(db, "v1")["img_01"]
    assert tally == {"real": 0, "synthetic": 1}


def test_vote_is_case_insensitive_per_user(tmp_path):
    db = tmp_path / "app.db"
    init_db(db)
    _vote_task(db)
    cast_vote(db, "v1", "img_01", "Alice", "real")
    cast_vote(db, "v1", "img_01", "alice", "synthetic")
    tally = get_vote_tallies(db, "v1")["img_01"]
    assert tally["real"] + tally["synthetic"] == 1


def test_tallies_aggregate_across_users(tmp_path):
    db = tmp_path / "app.db"
    init_db(db)
    _vote_task(db)
    cast_vote(db, "v1", "img_01", "Alice", "real")
    cast_vote(db, "v1", "img_01", "Bob", "real")
    cast_vote(db, "v1", "img_01", "Carol", "synthetic")
    assert get_vote_tallies(db, "v1")["img_01"] == {"real": 2, "synthetic": 1}


def test_tallies_include_images_with_no_votes(tmp_path):
    db = tmp_path / "app.db"
    init_db(db)
    _vote_task(db)
    tallies = get_vote_tallies(db, "v1")
    assert tallies == {
        "img_01": {"real": 0, "synthetic": 0},
        "img_02": {"real": 0, "synthetic": 0},
    }


def test_invalid_vote_label_rejected(tmp_path):
    db = tmp_path / "app.db"
    init_db(db)
    _vote_task(db)
    with pytest.raises(ValueError, match="Invalid vote"):
        cast_vote(db, "v1", "img_01", "Alice", "maybe")


def test_blank_user_rejected(tmp_path):
    db = tmp_path / "app.db"
    init_db(db)
    _vote_task(db)
    with pytest.raises(ValueError, match="user_name"):
        cast_vote(db, "v1", "img_01", "  ", "real")


def test_unknown_image_rejected(tmp_path):
    db = tmp_path / "app.db"
    init_db(db)
    _vote_task(db)
    with pytest.raises(ValueError, match="Unknown vote image"):
        cast_vote(db, "v1", "ghost", "Alice", "real")


def test_reset_task_votes_keeps_images(tmp_path):
    db = tmp_path / "app.db"
    init_db(db)
    _vote_task(db)
    cast_vote(db, "v1", "img_01", "Alice", "real")
    reset_task_votes(db, "v1")
    assert get_user_votes(db, "v1", "Alice") == {}
    assert len(get_vote_images(db, "v1")) == 2


def test_reset_all_votes(tmp_path):
    db = tmp_path / "app.db"
    init_db(db)
    _vote_task(db, task_id="v1")
    _vote_task(db, task_id="v2")
    cast_vote(db, "v1", "img_01", "Alice", "real")
    cast_vote(db, "v2", "img_01", "Bob", "synthetic")
    reset_all_votes(db)
    assert get_user_votes(db, "v1", "Alice") == {}
    assert get_user_votes(db, "v2", "Bob") == {}


def test_sync_removes_dropped_images_and_cascades_votes(tmp_path):
    db = tmp_path / "app.db"
    init_db(db)
    _vote_task(db, images=("img_01", "img_02"))
    cast_vote(db, "v1", "img_02", "Alice", "real")
    # Re-sync with img_02 dropped
    sync_vote_images(
        db,
        "v1",
        [VoteImage(id="img_01", image_path="x.png", label="real", sort_order=0)],
    )
    assert [i.id for i in get_vote_images(db, "v1")] == ["img_01"]
    # The vote for the removed image is gone (cascade)
    assert get_user_votes(db, "v1", "Alice") == {}
