from pathlib import Path

import pydantic
import pytest

from genai_cv_game.config import AppSettings, ensure_directories, load_settings


def test_defaults_without_env(monkeypatch):
    for var in [
        "APP_TITLE",
        "REPLICATE_API_TOKEN",
        "APP_PASSCODE",
        "INSTRUCTOR_PASSCODE",
        "DEFAULT_REPLICATE_MODEL",
        "DB_PATH",
        "ROUNDS_PATH",
        "GENERATED_DIR",
        "ASSETS_DIR",
        "USE_STUB_GENERATION",
    ]:
        monkeypatch.delenv(var, raising=False)

    s = load_settings()

    assert s.app_title == "Generative AI CV Classroom Game"
    assert s.replicate_api_token is None
    assert s.default_replicate_model is None
    assert s.app_passcode == "changeme"
    assert s.instructor_passcode == "changeme"
    assert isinstance(s.db_path, Path)
    assert isinstance(s.rounds_path, Path)
    assert s.use_stub_generation is False


def test_app_passcode_env_override(monkeypatch):
    monkeypatch.setenv("APP_PASSCODE", "let-me-in")
    assert load_settings().app_passcode == "let-me-in"


def test_env_override(monkeypatch):
    monkeypatch.setenv("APP_TITLE", "Test Game")
    monkeypatch.setenv("REPLICATE_API_TOKEN", "tok123")
    monkeypatch.setenv("DEFAULT_REPLICATE_MODEL", "some/model")

    s = load_settings()

    assert s.app_title == "Test Game"
    assert s.replicate_api_token == "tok123"
    assert s.default_replicate_model == "some/model"


def test_stub_flag_true(monkeypatch):
    for val in ("true", "True", "TRUE"):
        monkeypatch.setenv("USE_STUB_GENERATION", val)
        assert load_settings().use_stub_generation is True


def test_max_attempts_default(monkeypatch):
    monkeypatch.delenv("MAX_ATTEMPTS", raising=False)
    assert load_settings().max_attempts == 3


def test_max_attempts_override(monkeypatch):
    monkeypatch.setenv("MAX_ATTEMPTS", "5")
    assert load_settings().max_attempts == 5


def test_max_attempts_validation(monkeypatch):
    monkeypatch.setenv("MAX_ATTEMPTS", "0")
    with pytest.raises(pydantic.ValidationError):
        load_settings()


def test_max_attempts_malformed(monkeypatch):
    monkeypatch.setenv("MAX_ATTEMPTS", "banana")
    with pytest.raises(pydantic.ValidationError):
        load_settings()


def test_ensure_directories_creates_paths(tmp_path, monkeypatch):
    monkeypatch.delenv("REPLICATE_API_TOKEN", raising=False)

    settings = AppSettings(
        app_title="Test",
        replicate_api_token=None,
        app_passcode="x",
        instructor_passcode="x",
        default_replicate_model=None,
        db_path=tmp_path / "data" / "app.db",
        rounds_path=tmp_path / "data" / "rounds.json",
        models_path=tmp_path / "data" / "models.json",
        generated_dir=tmp_path / "generated",
        assets_dir=tmp_path / "assets",
        use_stub_generation=False,
    )

    ensure_directories(settings)

    assert (tmp_path / "data").is_dir()
    assert (tmp_path / "generated").is_dir()
    assert (tmp_path / "assets" / "target_images").is_dir()
    assert (tmp_path / "assets" / "placeholder").is_dir()
