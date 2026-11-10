"""Tests for the zoom helpers (ui/zoom.py), vote zoom groups and the image script."""

import importlib.util
from pathlib import Path

import pytest
import streamlit as st
from PIL import Image, JpegImagePlugin

from genai_cv_game.models import VoteImage
from genai_cv_game.ui import zoom
from genai_cv_game.ui.vote import _zoom_groups


def _jpg(path: Path, size: tuple[int, int]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, (90, 120, 150)).save(path, "JPEG")
    return path


def test_static_url_only_for_files_below_static():
    assert zoom.static_url("static/a/img 01.jpg") == "/app/static/a/img%2001.jpg"
    assert zoom.static_url("assets/a.jpg") is None
    assert zoom.static_url("/abs/static/a.jpg") is None


def test_static_url_respects_base_url_path(monkeypatch):
    real = st.get_option
    monkeypatch.setattr(
        st, "get_option", lambda k: "/class/" if k == "server.baseUrlPath" else real(k)
    )
    assert zoom.static_url("static/x.jpg") == "/class/app/static/x.jpg"


def test_zoom_variant_only_if_it_exists(tmp_path):
    img = _jpg(tmp_path / "img_01.jpg", (40, 30))
    assert zoom.zoom_variant(img) is None
    big = _jpg(tmp_path / "img_01_zoom.jpg", (80, 60))
    assert zoom.zoom_variant(img) == big.as_posix()


def test_same_aspect_tolerance(tmp_path):
    a = _jpg(tmp_path / "a.jpg", (200, 300))
    b = _jpg(tmp_path / "b.jpg", (400, 602))  # 0.3 % off
    c = _jpg(tmp_path / "c.jpg", (300, 200))
    assert zoom.same_aspect(a, b)
    assert not zoom.same_aspect(a, c)
    assert not zoom.same_aspect(a, tmp_path / "missing.jpg")


def test_zoom_image_declines_without_static_serving(tmp_path, monkeypatch):
    monkeypatch.setattr(zoom, "zoom_available", lambda: False)
    img = _jpg(tmp_path / "static" / "x.jpg", (10, 10))
    assert zoom.zoom_image(img, key="k", group=zoom.ZoomGroup("g"), alt="x") is False


class _Resp:
    def __init__(self, content_type, ok=True):
        self.headers = {"content-type": content_type}
        self.ok = ok

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture
def fresh_probe(monkeypatch):
    monkeypatch.setitem(zoom._probe, "at", -1e9)
    monkeypatch.setitem(zoom._probe, "ok", False)


def test_static_probe_accepts_images(fresh_probe, monkeypatch):
    monkeypatch.setattr(zoom.requests, "get", lambda *a, **k: _Resp("image/jpeg"))
    assert zoom.static_serving_works("/app/static/x.jpg") is True


def test_static_probe_rejects_catch_all_html_page(fresh_probe, monkeypatch):
    # A server started before static/ existed answers 200 with the app's HTML.
    monkeypatch.setattr(zoom.requests, "get", lambda *a, **k: _Resp("text/html"))
    assert zoom.static_serving_works("/app/static/x.jpg") is False


def test_static_probe_rejects_unreachable_server(fresh_probe, monkeypatch):
    def boom(*a, **k):
        raise zoom.requests.ConnectionError("nope")

    monkeypatch.setattr(zoom.requests, "get", boom)
    assert zoom.static_serving_works("/app/static/x.jpg") is False


def test_static_probe_result_is_reused(fresh_probe, monkeypatch):
    calls = []

    def get(*a, **k):
        calls.append(1)
        return _Resp("image/jpeg")

    monkeypatch.setattr(zoom.requests, "get", get)
    assert zoom.static_serving_works("/app/static/x.jpg")
    assert zoom.static_serving_works("/app/static/y.jpg")
    assert len(calls) == 1


def test_zoom_image_declines_when_server_does_not_serve_static(tmp_path, monkeypatch):
    monkeypatch.setattr(zoom, "zoom_available", lambda: True)
    monkeypatch.setattr(zoom, "static_serving_works", lambda url: False)
    img = _jpg(Path("static") / "_probe_test" / "x.jpg", (10, 10))
    try:
        assert (
            zoom.zoom_image(img, key="k", group=zoom.ZoomGroup("g"), alt="x") is False
        )
    finally:
        img.unlink()
        img.parent.rmdir()


def test_zoom_image_declines_for_files_outside_static(monkeypatch):
    monkeypatch.setattr(zoom, "zoom_available", lambda: True)
    assert (
        zoom.zoom_image(
            "assets/placeholder/stub.png", key="k", group=zoom.ZoomGroup("g"), alt="x"
        )
        is False
    )


def _vote_image(tmp_path, name, size, pair="p"):
    path = _jpg(tmp_path / f"{name}.jpg", size)
    return VoteImage(
        id=name, task_id="t", image_path=str(path), label="real", pair=pair
    )


def test_pair_zoom_groups_share_id_and_sync_only_for_same_aspect(tmp_path):
    a = _vote_image(tmp_path, "a", (200, 300))
    b = _vote_image(tmp_path, "b", (400, 600))
    g = _zoom_groups([a, b], "vote")
    assert [x.id for x in g] == ["vote:t:p", "vote:t:p"]
    assert [x.pos for x in g] == [0, 1]
    assert all(x.sync for x in g)

    c = _vote_image(tmp_path, "c", (600, 400))
    assert not any(x.sync for x in _zoom_groups([a, c], "vote"))


def test_single_image_group_is_unsynced_and_scoped(tmp_path):
    a = _vote_image(tmp_path, "a", (200, 300), pair="")
    (g,) = _zoom_groups([a], "results")
    assert g == zoom.ZoomGroup("results:t:a", 0, False)


# ── scripts/prepare_vote_images.py ───────────────────────────────────────────


@pytest.fixture(scope="module")
def prep():
    spec = importlib.util.spec_from_file_location(
        "prep_zoom", Path("scripts/prepare_vote_images.py")
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.parametrize("size", [(600, 900), (4000, 2500), (1280, 700)])
def test_normalise_gives_exact_long_edges_for_any_source(prep, tmp_path, size):
    src = _jpg(tmp_path / "src.jpg", size)
    page, big = tmp_path / "o" / "img.jpg", tmp_path / "o" / "img_zoom.jpg"
    prep.normalise(src, page, big, long_edge=200, zoom_edge=320)
    with Image.open(page) as p, Image.open(big) as z:
        assert max(p.size) == 200 and max(z.size) == 320
        assert p.format == z.format == "JPEG"
        # Full colour resolution (4:4:4) for every image, same settings for all.
        assert JpegImagePlugin.get_sampling(p) == JpegImagePlugin.get_sampling(z) == 0
        assert abs(p.width / p.height - size[0] / size[1]) < 0.02
        assert not p.getexif()


def test_normalise_without_zoom_writes_one_file(prep, tmp_path):
    src = _jpg(tmp_path / "src.jpg", (300, 200))
    prep.normalise(src, tmp_path / "only.jpg", None, long_edge=100)
    assert {f.name for f in tmp_path.glob("*.jpg")} == {"src.jpg", "only.jpg"}
