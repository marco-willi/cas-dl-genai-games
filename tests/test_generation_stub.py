import shutil
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import requests

from genai_cv_game.config import AppSettings
from genai_cv_game.db import (
    choose_submission,
    create_submission,
    init_db,
    insert_or_update_round,
    update_submission_status,
)
from genai_cv_game.generation import (
    _extract_url,
    poll_generation,
    start_generation,
)
from genai_cv_game.models import Round
from genai_cv_game.storage import (
    download_image,
    export_submissions_csv,
    make_submission_image_path,
)


# ── storage ──────────────────────────────────────────────────────────────────


def test_make_submission_image_path(tmp_path):
    p = make_submission_image_path(tmp_path / "generated", "r1", "sub1")
    assert p == tmp_path / "generated" / "r1" / "sub1.png"
    assert p.parent.is_dir()


def test_download_image_success(tmp_path, monkeypatch):
    fake = MagicMock()
    fake.content = b"\x89PNG fake"
    fake.raise_for_status = MagicMock()
    monkeypatch.setattr("genai_cv_game.storage.requests.get", lambda *a, **kw: fake)

    out = tmp_path / "img.png"
    result = download_image("http://example.com/img.png", out)
    assert result == out
    assert out.read_bytes() == b"\x89PNG fake"


def test_download_image_http_error(tmp_path, monkeypatch):
    def bad_get(*a, **kw):
        r = MagicMock()
        r.raise_for_status.side_effect = requests.HTTPError("404")
        return r

    monkeypatch.setattr("genai_cv_game.storage.requests.get", bad_get)
    with pytest.raises(RuntimeError, match="Failed to download"):
        download_image("http://example.com/img.png", tmp_path / "img.png")


def test_download_image_network_error(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "genai_cv_game.storage.requests.get",
        lambda *a, **kw: (_ for _ in ()).throw(ConnectionError("unreachable")),
    )
    with pytest.raises(RuntimeError, match="Failed to download"):
        download_image("http://example.com/img.png", tmp_path / "img.png")


def test_export_submissions_csv(tmp_path):
    db = tmp_path / "app.db"
    init_db(db)
    insert_or_update_round(
        db, Round(id="r1", title="T", description="d", mode="business")
    )
    s1 = create_submission(db, "r1", "Team A", "blue car", max_attempts=3)
    s2 = create_submission(db, "r1", "Team B", "red sky", max_attempts=3)
    update_submission_status(db, s1, "completed", image_path="generated/r1/s1.png")
    update_submission_status(db, s2, "completed", image_path="generated/r1/s2.png")
    choose_submission(db, s1)
    choose_submission(db, s2)

    data = export_submissions_csv(db, "r1", round_title="My Round")
    text = data.decode()
    assert "round_title" in text
    assert "My Round" in text
    assert "team_name" in text
    assert "Team A" in text
    assert "Team B" in text
    assert "blue car" in text


# ── generation ───────────────────────────────────────────────────────────────


def _settings(tmp_path, *, stub=True, token=None, model=None) -> AppSettings:
    placeholder = tmp_path / "assets" / "placeholder"
    placeholder.mkdir(parents=True)
    if stub:
        shutil.copy(Path("assets/placeholder/stub.png"), placeholder / "stub.png")
    return AppSettings(
        app_title="Test",
        replicate_api_token=token,
        app_passcode="x",
        instructor_passcode="x",
        default_replicate_model=model,
        db_path=tmp_path / "app.db",
        rounds_path=tmp_path / "rounds.json",
        models_path=tmp_path / "models.json",
        generated_dir=tmp_path / "generated",
        assets_dir=tmp_path / "assets",
        use_stub_generation=stub,
    )


def test_stub_start_writes_image_and_returns_sentinel(tmp_path):
    s = _settings(tmp_path, stub=True)
    pred_id = start_generation("a prompt", "r1", "sub1", s)
    assert pred_id.startswith("stub:")
    expected = s.generated_dir / "r1" / "sub1.png"
    assert expected.exists()


def test_stub_poll_returns_succeeded(tmp_path):
    s = _settings(tmp_path, stub=True)
    pred_id = start_generation("a prompt", "r1", "sub1", s)
    result = poll_generation(pred_id, "r1", "sub1", s)
    assert result.status == "succeeded"
    assert result.image_path is not None
    assert Path(result.image_path).exists()


def test_stub_poll_failed_if_image_missing(tmp_path):
    s = _settings(tmp_path, stub=True)
    pred_id = start_generation("a prompt", "r1", "sub1", s)
    Path(s.generated_dir / "r1" / "sub1.png").unlink()
    result = poll_generation(pred_id, "r1", "sub1", s)
    assert result.status == "failed"


def test_stub_start_missing_placeholder(tmp_path):
    s = _settings(tmp_path, stub=True)
    (s.assets_dir / "placeholder" / "stub.png").unlink()
    with pytest.raises((FileNotFoundError, shutil.Error)):
        start_generation("a prompt", "r1", "sub1", s)


def test_start_missing_token(tmp_path):
    s = _settings(tmp_path, stub=False, token=None, model="some/model")
    with pytest.raises(RuntimeError, match="token"):
        start_generation("a prompt", "r1", "sub1", s)


def test_start_missing_model(tmp_path):
    s = _settings(tmp_path, stub=False, token="tok", model=None)
    with pytest.raises(RuntimeError, match="model"):
        start_generation("a prompt", "r1", "sub1", s)


def test_real_start_returns_prediction_id(tmp_path, monkeypatch):
    fake_prediction = MagicMock()
    fake_prediction.id = "pred_abc"
    fake_client = MagicMock()
    fake_client.predictions.create.return_value = fake_prediction
    monkeypatch.setattr(
        "genai_cv_game.generation.replicate.Client", lambda api_token: fake_client
    )
    monkeypatch.setattr(
        "genai_cv_game.generation._resolve_version", lambda client, model: "v1"
    )

    s = _settings(tmp_path, stub=False, token="tok", model="some/model")
    pred_id = start_generation("a prompt", "r1", "sub1", s)
    assert pred_id == "pred_abc"
    fake_client.predictions.create.assert_called_once_with(
        version="v1", input={"prompt": "a prompt"}
    )


def test_real_start_with_image_input_passes_file_handles(tmp_path, monkeypatch):
    img = tmp_path / "src.png"
    img.write_bytes(b"\x89PNG fake")

    captured = {}

    def fake_create(*, version, input):
        captured["version"] = version
        captured["input"] = input
        fake_prediction = MagicMock()
        fake_prediction.id = "pred_img"
        return fake_prediction

    fake_client = MagicMock()
    fake_client.predictions.create.side_effect = fake_create
    monkeypatch.setattr(
        "genai_cv_game.generation.replicate.Client", lambda api_token: fake_client
    )
    monkeypatch.setattr(
        "genai_cv_game.generation._resolve_version", lambda client, model: "v1"
    )

    s = _settings(tmp_path, stub=False, token="tok", model="some/model")
    pred_id = start_generation("a prompt", "r1", "sub1", s, image_input_paths=[img])
    assert pred_id == "pred_img"
    assert "image_input" in captured["input"]
    handles = captured["input"]["image_input"]
    assert len(handles) == 1
    assert handles[0].name == str(img)


def test_real_start_without_image_input_omits_field(tmp_path, monkeypatch):
    captured = {}

    def fake_create(*, version, input):
        captured["input"] = input
        fake_prediction = MagicMock()
        fake_prediction.id = "pred_text"
        return fake_prediction

    fake_client = MagicMock()
    fake_client.predictions.create.side_effect = fake_create
    monkeypatch.setattr(
        "genai_cv_game.generation.replicate.Client", lambda api_token: fake_client
    )
    monkeypatch.setattr(
        "genai_cv_game.generation._resolve_version", lambda client, model: "v1"
    )

    s = _settings(tmp_path, stub=False, token="tok", model="some/model")
    start_generation("a prompt", "r1", "sub1", s)
    assert "image_input" not in captured["input"]


def test_real_start_wraps_errors(tmp_path, monkeypatch):
    fake_client = MagicMock()
    fake_client.predictions.create.side_effect = RuntimeError("boom")
    monkeypatch.setattr(
        "genai_cv_game.generation.replicate.Client", lambda api_token: fake_client
    )
    monkeypatch.setattr(
        "genai_cv_game.generation._resolve_version", lambda client, model: "v1"
    )

    s = _settings(tmp_path, stub=False, token="tok", model="some/model")
    with pytest.raises(RuntimeError, match="Failed to start generation"):
        start_generation("a prompt", "r1", "sub1", s)


def test_real_poll_processing_returns_pending(tmp_path, monkeypatch):
    fake_prediction = MagicMock()
    fake_prediction.status = "processing"
    fake_client = MagicMock()
    fake_client.predictions.get.return_value = fake_prediction
    monkeypatch.setattr(
        "genai_cv_game.generation.replicate.Client", lambda api_token: fake_client
    )

    s = _settings(tmp_path, stub=False, token="tok", model="some/model")
    result = poll_generation("pred_abc", "r1", "sub1", s)
    assert result.status == "pending"


def test_real_poll_succeeded_downloads_and_returns_path(tmp_path, monkeypatch):
    fake_png = Path("assets/placeholder/stub.png").read_bytes()
    fake_response = MagicMock()
    fake_response.content = fake_png
    fake_response.raise_for_status = MagicMock()
    monkeypatch.setattr(
        "genai_cv_game.storage.requests.get", lambda *a, **kw: fake_response
    )

    fake_prediction = MagicMock()
    fake_prediction.status = "succeeded"
    fake_prediction.output = "http://example.com/out.png"
    fake_client = MagicMock()
    fake_client.predictions.get.return_value = fake_prediction
    monkeypatch.setattr(
        "genai_cv_game.generation.replicate.Client", lambda api_token: fake_client
    )

    s = _settings(tmp_path, stub=False, token="tok", model="some/model")
    result = poll_generation("pred_abc", "r1", "sub1", s)
    assert result.status == "succeeded"
    assert result.image_path is not None
    assert Path(result.image_path).exists()


def test_real_poll_failed_reports_error(tmp_path, monkeypatch):
    fake_prediction = MagicMock()
    fake_prediction.status = "failed"
    fake_prediction.error = "model timed out"
    fake_client = MagicMock()
    fake_client.predictions.get.return_value = fake_prediction
    monkeypatch.setattr(
        "genai_cv_game.generation.replicate.Client", lambda api_token: fake_client
    )

    s = _settings(tmp_path, stub=False, token="tok", model="some/model")
    result = poll_generation("pred_abc", "r1", "sub1", s)
    assert result.status == "failed"
    assert "model timed out" in (result.error or "")


def test_real_poll_get_error_returns_failed(tmp_path, monkeypatch):
    fake_client = MagicMock()
    fake_client.predictions.get.side_effect = RuntimeError("network down")
    monkeypatch.setattr(
        "genai_cv_game.generation.replicate.Client", lambda api_token: fake_client
    )

    s = _settings(tmp_path, stub=False, token="tok", model="some/model")
    result = poll_generation("pred_abc", "r1", "sub1", s)
    assert result.status == "failed"
    assert "network down" in (result.error or "")


# ── _extract_url ─────────────────────────────────────────────────────────────


def test_extract_url_string():
    assert _extract_url("http://x.com/a.png") == "http://x.com/a.png"


def test_extract_url_list():
    assert (
        _extract_url(["http://x.com/a.png", "http://x.com/b.png"])
        == "http://x.com/a.png"
    )


def test_extract_url_iterator():
    assert _extract_url(iter(["http://x.com/a.png"])) == "http://x.com/a.png"


def test_extract_url_empty_raises():
    with pytest.raises(RuntimeError, match="Unexpected output"):
        _extract_url([])
