from __future__ import annotations

import csv
import io
import shutil
from pathlib import Path

import requests

from genai_cv_game.db import get_submissions_for_round


def make_submission_image_path(
    generated_dir: Path,
    round_id: str,
    submission_id: str,
) -> Path:
    path = generated_dir / round_id / f"{submission_id}.png"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def clear_generated_dir(generated_dir: Path) -> None:
    """Remove every per-round subdirectory under generated_dir. Top dir survives."""
    if not generated_dir.exists():
        return
    for child in generated_dir.iterdir():
        if child.is_dir():
            shutil.rmtree(child)
        else:
            # Preserve dotfiles like .gitkeep so the directory remains tracked.
            if not child.name.startswith("."):
                child.unlink()


def download_image(url: str, output_path: Path) -> Path:
    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()
    except Exception as e:
        raise RuntimeError(f"Failed to download generated image: {e}") from e
    output_path.write_bytes(response.content)
    return output_path


def export_submissions_csv(
    db_path: Path, round_id: str, round_title: str = ""
) -> bytes:
    submissions = get_submissions_for_round(db_path, round_id)
    fields = [
        "round_id",
        "round_title",
        "team_name",
        "prompt",
        "image_path",
        "status",
        "error_message",
        "created_at",
    ]
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    for s in submissions:
        row = s.model_dump()
        row["round_title"] = round_title
        writer.writerow(row)
    return buf.getvalue().encode()
