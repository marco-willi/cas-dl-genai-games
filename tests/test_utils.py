from datetime import datetime

from genai_cv_game.utils import new_id, now_utc, slugify


def test_new_id_is_unique():
    assert new_id() != new_id()


def test_new_id_is_string():
    assert isinstance(new_id(), str)


def test_now_utc_is_iso_string():
    datetime.fromisoformat(now_utc())


def test_slugify():
    assert slugify("Hello World") == "hello_world"
