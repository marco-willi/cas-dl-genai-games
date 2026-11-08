"""Tests for likes, vote reveal/scores, class stats, migrations and helpers."""

import io
import json
import sqlite3
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from PIL import Image

from genai_cv_game.db import (
    cast_vote,
    create_generation,
    delete_generation,
    get_class_stats,
    get_reaction_counts,
    get_task,
    get_user_reactions,
    get_vote_images,
    get_vote_scores,
    init_db,
    insert_or_update_task,
    is_vote_revealed,
    set_vote_revealed,
    sync_vote_images,
    toggle_reaction,
    update_generation_status,
)
from genai_cv_game.model_catalog import display_name, load_models
from genai_cv_game.models import Task, VoteImage
from genai_cv_game.storage import save_uploaded_input_image
from genai_cv_game.utils import md_escape, plural, truncate


def _db(tmp_path, mode="text2img"):
    db = tmp_path / "app.db"
    init_db(db)
    insert_or_update_task(db, Task(id="t1", title="T", description="d", mode=mode))
    return db


# ── Reactions ────────────────────────────────────────────────────────────────


def test_toggle_reaction_likes_and_unlikes(tmp_path):
    db = _db(tmp_path)
    gid = create_generation(db, "t1", "Alice", "p", 3)
    assert toggle_reaction(db, gid, "Bob") is True
    assert toggle_reaction(db, gid, "carol") is True
    assert get_reaction_counts(db, "t1") == {gid: 2}
    assert get_user_reactions(db, "t1", "BOB") == {gid}
    assert toggle_reaction(db, gid, "bob") is False
    assert get_reaction_counts(db, "t1") == {gid: 1}


def test_cannot_like_own_or_unknown(tmp_path):
    db = _db(tmp_path)
    gid = create_generation(db, "t1", "Alice", "p", 3)
    with pytest.raises(ValueError, match="own"):
        toggle_reaction(db, gid, "alice")
    with pytest.raises(ValueError, match="Unknown"):
        toggle_reaction(db, "nope", "Bob")


def test_reactions_cascade_with_generation(tmp_path):
    db = _db(tmp_path)
    gid = create_generation(db, "t1", "Alice", "p", 3)
    toggle_reaction(db, gid, "Bob")
    delete_generation(db, gid)
    assert get_reaction_counts(db, "t1") == {}


# ── Vote reveal / scores / hints ─────────────────────────────────────────────


def _vote_db(tmp_path):
    db = _db(tmp_path, mode="vote")
    img = str(Path("assets/placeholder/stub.png"))
    sync_vote_images(
        db,
        "t1",
        [
            VoteImage(id="a", image_path=img, label="real", hint="look at the hands"),
            VoteImage(id="b", image_path=img, label="synthetic"),
        ],
    )
    return db


def test_reveal_flag_per_task(tmp_path):
    db = _vote_db(tmp_path)
    assert is_vote_revealed(db, "t1") is False
    set_vote_revealed(db, "t1", True)
    assert is_vote_revealed(db, "t1") is True
    assert is_vote_revealed(db, "other") is False


def test_vote_scores_ranked(tmp_path):
    db = _vote_db(tmp_path)
    cast_vote(db, "t1", "a", "Alice", "real")
    cast_vote(db, "t1", "b", "Alice", "synthetic")
    cast_vote(db, "t1", "a", "Bob", "synthetic")
    cast_vote(db, "t1", "a", "Bob", "real")  # change of mind counts once
    scores = get_vote_scores(db, "t1")
    assert [(s.user_name, s.correct, s.voted) for s in scores] == [
        ("Alice", 2, 2),
        ("Bob", 1, 1),
    ]


def test_vote_hint_round_trips(tmp_path):
    db = _vote_db(tmp_path)
    hints = {i.id: i.hint for i in get_vote_images(db, "t1")}
    assert hints == {"a": "look at the hands", "b": ""}


def test_sync_vote_images_empty_list_removes_all(tmp_path):
    db = _vote_db(tmp_path)
    sync_vote_images(db, "t1", [])
    assert get_vote_images(db, "t1") == []


# ── Class stats ──────────────────────────────────────────────────────────────


def test_class_stats(tmp_path):
    db = _vote_db(tmp_path)
    g1 = create_generation(db, "t1", "Alice", "p", 5)
    g2 = create_generation(db, "t1", "Alice", "p", 5)
    update_generation_status(db, g1, "completed", image_path="x.png")
    update_generation_status(db, g2, "failed", error_message="e")
    cast_vote(db, "t1", "a", "Bob", "real")
    s = get_class_stats(db)
    assert (s.participants, s.generations, s.completed, s.failed) == (2, 2, 1, 1)
    assert s.avg_seconds is not None and s.avg_seconds >= 0


# ── Migration of an old database ─────────────────────────────────────────────


def test_init_db_migrates_old_schema(tmp_path):
    db = tmp_path / "old.db"
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE tasks (id TEXT PRIMARY KEY, title TEXT NOT NULL,
            description TEXT NOT NULL, mode TEXT NOT NULL, target_image_path TEXT,
            input_image_paths TEXT NOT NULL DEFAULT '[]',
            is_available INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
        INSERT INTO tasks VALUES ('old', 'Old', 'd', 'business', NULL, '[]', 1, '1', '1');
        CREATE TABLE vote_images (id TEXT NOT NULL, task_id TEXT NOT NULL,
            image_path TEXT NOT NULL, label TEXT NOT NULL,
            sort_order INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL, PRIMARY KEY (task_id, id));
        """
    )
    conn.commit()
    conn.close()
    init_db(db)
    task = get_task(db, "old")
    assert task is not None and task.mode == "text2img" and task.nav_title is None
    cols = {r[1] for r in sqlite3.connect(db).execute("PRAGMA table_info(vote_images)")}
    assert "hint" in cols


# ── Model catalog ────────────────────────────────────────────────────────────


def test_model_catalog_defaults_and_cache(tmp_path):
    path = tmp_path / "models.json"
    path.write_text(json.dumps([{"id": "a", "slug": "o/a", "display_name": "A"}]))
    (m,) = load_models(path)
    assert m.image_input_field == "image_input" and m.supports_seed is False
    assert display_name(path, "o/a") == "A"
    assert display_name(path, "o/unknown") == "o/unknown"


# ── Upload normalisation ─────────────────────────────────────────────────────


def _image_bytes(size, mode="RGB", fmt="JPEG"):
    buf = io.BytesIO()
    Image.new(mode, size).save(buf, fmt)
    return buf.getvalue()


def test_upload_downscaled_to_jpeg(tmp_path):
    dest = save_uploaded_input_image(tmp_path, "t1", "g1", _image_bytes((4000, 2000)))
    assert dest.suffix == ".jpg"
    with Image.open(dest) as im:
        assert max(im.size) == 1536


def test_upload_with_alpha_stays_png(tmp_path):
    dest = save_uploaded_input_image(
        tmp_path, "t1", "g1", _image_bytes((100, 100), mode="RGBA", fmt="PNG")
    )
    assert dest.suffix == ".png"


def test_upload_rejects_garbage(tmp_path):
    with pytest.raises(ValueError, match="uploaded image"):
        save_uploaded_input_image(tmp_path, "t1", "g1", b"not an image")


# ── Generation payload ───────────────────────────────────────────────────────


def test_start_generation_payload_with_seed_and_pinned_version(tmp_path, monkeypatch):
    from genai_cv_game.config import AppSettings
    from genai_cv_game.generation import start_generation

    fake_client = MagicMock()
    fake_client.predictions.create.return_value = MagicMock(id="p1")
    monkeypatch.setattr(
        "genai_cv_game.generation.replicate.Client", lambda api_token: fake_client
    )
    img = tmp_path / "src.png"
    img.write_bytes(b"x")
    s = AppSettings(
        app_title="T",
        replicate_api_token="tok",
        app_passcode="x",
        instructor_passcode="x",
        default_replicate_model=None,
        db_path=tmp_path / "a.db",
        tasks_path=tmp_path / "t.json",
        models_path=tmp_path / "m.json",
        generated_dir=tmp_path / "g",
        assets_dir=tmp_path / "a",
        use_stub_generation=False,
    )
    start_generation(
        "p",
        "t1",
        "g1",
        s,
        model_slug="o/m:v9",
        image_input_paths=[img],
        image_input_field="input_images",
        seed=3,
    )
    kwargs = fake_client.predictions.create.call_args.kwargs
    assert kwargs["version"] == "v9"
    assert kwargs["input"]["seed"] == 3
    assert len(kwargs["input"]["input_images"]) == 1
    assert "image_input" not in kwargs["input"]


# ── Utils ────────────────────────────────────────────────────────────────────


def test_md_escape_neutralises_markdown():
    assert md_escape("# *hi* [x](y) $a$ :red[z]") == (
        r"\# \*hi\* \[x\]\(y\) \$a\$ \:red\[z\]"
    )


def test_plural_and_truncate():
    assert plural(1, "slot") == "1 slot"
    assert plural(2, "slot") == "2 slots"
    assert truncate("a  b\nc", 10) == "a b c"
    assert truncate("abcdefghij", 5) == "abcd…"


# ── Vote pairs ───────────────────────────────────────────────────────────────


def _vote_task_file(tmp_path, images):
    path = tmp_path / "tasks.json"
    path.write_text(
        json.dumps(
            [
                {
                    "id": "v",
                    "title": "V",
                    "description": "d",
                    "mode": "vote",
                    "vote_images": images,
                }
            ]
        )
    )
    return path


_IMG = "assets/placeholder/stub.png"


def test_vote_pairs_load_and_round_trip(tmp_path):
    from genai_cv_game.tasks import load_task_definitions, sync_tasks_from_json

    path = _vote_task_file(
        tmp_path,
        [
            {"id": "a", "path": _IMG, "label": "synthetic", "pair": "p1"},
            {"id": "b", "path": _IMG, "label": "real", "pair": "p1"},
            {"id": "c", "path": _IMG, "label": "real"},
        ],
    )
    (task,) = load_task_definitions(path)
    assert [i.pair for i in task.vote_images] == ["p1", "p1", ""]
    db = tmp_path / "app.db"
    sync_tasks_from_json(path, db)
    assert [(i.id, i.pair) for i in get_vote_images(db, "v")] == [
        ("a", "p1"),
        ("b", "p1"),
        ("c", ""),
    ]


@pytest.mark.parametrize(
    ("images", "match"),
    [
        (
            [
                {"id": "a", "path": _IMG, "label": "real", "pair": "p"},
                {"id": "b", "path": _IMG, "label": "real", "pair": "p"},
            ],
            "exactly one 'real' and one 'synthetic'",
        ),
        (
            [
                {"id": "a", "path": _IMG, "label": "real", "pair": "p"},
                {"id": "x", "path": _IMG, "label": "real"},
                {"id": "b", "path": _IMG, "label": "synthetic", "pair": "p"},
                {"id": "c", "path": _IMG, "label": "real", "pair": "q"},
                {"id": "d", "path": _IMG, "label": "synthetic", "pair": "q"},
            ],
            None,  # unpaired image in between is fine: pairs are still adjacent
        ),
        (
            [
                {"id": "a", "path": _IMG, "label": "real", "pair": "p"},
                {"id": "c", "path": _IMG, "label": "real", "pair": "q"},
                {"id": "b", "path": _IMG, "label": "synthetic", "pair": "p"},
                {"id": "d", "path": _IMG, "label": "synthetic", "pair": "q"},
            ],
            "next to each other",
        ),
    ],
)
def test_vote_pair_validation(tmp_path, images, match):
    from genai_cv_game.tasks import load_task_definitions

    path = _vote_task_file(tmp_path, images)
    if match is None:
        load_task_definitions(path)
    else:
        with pytest.raises(ValueError, match=match):
            load_task_definitions(path)


def test_prepare_script_keeps_pairs_adjacent_and_randomises_sides():
    import importlib.util
    import random

    spec = importlib.util.spec_from_file_location(
        "prep", Path("scripts/prepare_vote_images.py")
    )
    prep = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(prep)

    entries = [
        {"path": f"{p}-{lab}", "label": lab, "pair": p}
        for p in "abcdefgh"
        for lab in ("real", "synthetic")
    ] + [{"path": "single", "label": "real"}]
    first_sides = set()
    for seed in range(20):
        ordered = prep._order([dict(e) for e in entries], random.Random(seed))
        assert sorted(e["path"] for e in ordered) == sorted(e["path"] for e in entries)
        paired = [e for e in ordered if e.get("pair")]
        for i in range(0, len(paired), 2):
            assert paired[i]["pair"] == paired[i + 1]["pair"]
            first_sides.add(paired[i]["label"])
    assert first_sides == {"real", "synthetic"}  # both sides occur


def test_prepare_script_respects_pair_order():
    import importlib.util
    import random

    spec = importlib.util.spec_from_file_location(
        "prep", Path("scripts/prepare_vote_images.py")
    )
    prep = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(prep)

    order = {"hard": 3, "easy": 1, "mid": 2}
    entries = [
        {"path": f"{p}-{lab}", "label": lab, "pair": p, "order": n}
        for p, n in order.items()
        for lab in ("real", "synthetic")
    ]
    for seed in range(10):
        ordered = prep._order([dict(e) for e in entries], random.Random(seed))
        assert [e["pair"] for e in ordered] == ["easy"] * 2 + ["mid"] * 2 + ["hard"] * 2
