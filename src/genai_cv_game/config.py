from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, Field

load_dotenv()


class AppSettings(BaseModel):
    app_title: str
    replicate_api_token: str | None
    app_passcode: str
    instructor_passcode: str
    default_replicate_model: str | None
    db_path: Path
    rounds_path: Path
    models_path: Path
    generated_dir: Path
    assets_dir: Path
    use_stub_generation: bool
    max_attempts: int = Field(default=3, ge=1, le=20)


def load_settings() -> AppSettings:
    raw: dict[str, object] = {
        "app_title": os.getenv("APP_TITLE", "Generative AI CV Classroom Game"),
        "replicate_api_token": os.getenv("REPLICATE_API_TOKEN") or None,
        "app_passcode": os.getenv("APP_PASSCODE", "changeme"),
        "instructor_passcode": os.getenv("INSTRUCTOR_PASSCODE", "changeme"),
        "default_replicate_model": os.getenv("DEFAULT_REPLICATE_MODEL") or None,
        "db_path": Path(os.getenv("DB_PATH", "data/app.db")),
        "rounds_path": Path(os.getenv("ROUNDS_PATH", "data/rounds.json")),
        "models_path": Path(os.getenv("MODELS_PATH", "data/models.json")),
        "generated_dir": Path(os.getenv("GENERATED_DIR", "generated")),
        "assets_dir": Path(os.getenv("ASSETS_DIR", "assets")),
        "use_stub_generation": os.getenv("USE_STUB_GENERATION", "false").lower()
        == "true",
    }
    if (raw_max := os.getenv("MAX_ATTEMPTS")) is not None:
        raw["max_attempts"] = raw_max
    return AppSettings.model_validate(raw)


def ensure_directories(settings: AppSettings) -> None:
    settings.db_path.parent.mkdir(parents=True, exist_ok=True)
    settings.generated_dir.mkdir(parents=True, exist_ok=True)
    (settings.assets_dir / "target_images").mkdir(parents=True, exist_ok=True)
    (settings.assets_dir / "placeholder").mkdir(parents=True, exist_ok=True)
