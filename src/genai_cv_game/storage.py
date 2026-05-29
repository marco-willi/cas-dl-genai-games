from __future__ import annotations

import csv
import io
import shutil
from pathlib import Path

import requests

from genai_cv_game.db import (
    get_gallery_generations,
    get_vote_images,
    get_vote_tallies,
)


def make_submission_image_path(
    generated_dir: Path,
    task_id: str,
    generation_id: str,
) -> Path:
    path = generated_dir / task_id / f"{generation_id}.png"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def save_uploaded_input_image(
    generated_dir: Path,
    task_id: str,
    generation_id: str,
    data: bytes,
    suffix: str,
) -> Path:
    """Persist a student-uploaded source image next to its generation.

    Used by explore-mode tasks, where the image to edit comes from a file
    upload rather than a path declared in the task. The saved file is then
    handed to `start_generation` as the model's image input.
    """
    suffix = suffix if suffix.startswith(".") else f".{suffix}"
    dest = generated_dir / task_id / f"{generation_id}_input{suffix}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    return dest


def clear_generated_dir(generated_dir: Path) -> None:
    """Remove every per-task subdirectory under generated_dir. Top dir survives."""
    if not generated_dir.exists():
        return
    for child in generated_dir.iterdir():
        if child.is_dir():
            shutil.rmtree(child)
        else:
            # Preserve dotfiles like .gitkeep so the directory remains tracked.
            if not child.name.startswith("."):
                child.unlink()


def clear_task_generated_dir(generated_dir: Path, task_id: str) -> None:
    """Remove the per-task subdirectory of generated images for one task."""
    task_dir = generated_dir / task_id
    if task_dir.is_dir():
        shutil.rmtree(task_dir)


def download_image(url: str, output_path: Path) -> Path:
    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()
    except Exception as e:
        raise RuntimeError(f"Failed to download generated image: {e}") from e
    output_path.write_bytes(response.content)
    return output_path


def export_gallery_csv(db_path: Path, task_id: str, task_title: str = "") -> bytes:
    generations = get_gallery_generations(db_path, task_id)
    fields = [
        "task_id",
        "task_title",
        "user_name",
        "prompt",
        "model_slug",
        "image_path",
        "status",
        "error_message",
        "created_at",
    ]
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    for g in generations:
        row = g.model_dump()
        row["task_title"] = task_title
        writer.writerow(row)
    return buf.getvalue().encode()


def export_votes_csv(db_path: Path, task_id: str, task_title: str = "") -> bytes:
    """Per-image vote tally for a vote-mode task: counts and true label."""
    images = get_vote_images(db_path, task_id)
    tallies = get_vote_tallies(db_path, task_id)
    fields = [
        "task_id",
        "task_title",
        "image_id",
        "image_path",
        "true_label",
        "real_votes",
        "synthetic_votes",
        "total_votes",
    ]
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    for img in images:
        tally = tallies.get(img.id, {"real": 0, "synthetic": 0})
        writer.writerow(
            {
                "task_id": task_id,
                "task_title": task_title,
                "image_id": img.id,
                "image_path": img.image_path,
                "true_label": img.label,
                "real_votes": tally["real"],
                "synthetic_votes": tally["synthetic"],
                "total_votes": tally["real"] + tally["synthetic"],
            }
        )
    return buf.getvalue().encode()
