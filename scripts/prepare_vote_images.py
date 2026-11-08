"""Normalise vote-game images so file properties don't leak the answer.

Real photos and AI images usually differ in format (JPEG vs PNG), resolution and
metadata — students can tell them apart by right-clicking. This script reads a
manifest of *original* images, re-encodes every image to the same format, long
edge and quality (metadata stripped), gives them neutral names in a shuffled
order, and rewrites the task's `vote_images` block in `tasks.json`. Images
sharing a `pair` value (real + AI version of the same scene) stay adjacent,
with a random side per pair, so the app shows them side by side.

Originals are never modified.

Usage:
    uv run python scripts/prepare_vote_images.py \
        --manifest assets/vote_images/spot_the_fake/manifest.json \
        --task-id spot_the_fake

Manifest format (list):
    [{"path": "assets/.../original.png", "label": "synthetic", "pair": "portrait",
      "order": 5, "hint": "..."}, ...]

`pair`, `order` (position of the pair, e.g. hardest last) and `hint` are
optional. For a pair, put the hint on one image (usually the AI one): the app
shows a pair's hints once, under both images.
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

from PIL import Image, ImageOps

LONG_EDGE = 1280
QUALITY = 85


def normalise(src: Path, dest: Path) -> None:
    with Image.open(src) as im:
        im = ImageOps.exif_transpose(im).convert("RGB")
        im.thumbnail((LONG_EDGE, LONG_EDGE), Image.Resampling.LANCZOS)
        dest.parent.mkdir(parents=True, exist_ok=True)
        # No exif/icc passed -> metadata stripped.
        im.save(dest, "JPEG", quality=QUALITY, optimize=True)


def _order(entries: list[dict], rng: random.Random) -> list[dict]:
    """Shuffle the images; keep paired images adjacent.

    Entries with the same `pair` value (one real + one AI version of the same
    scene) stay next to each other so the app can show them side by side. The
    order of the pairs is shuffled unless entries carry an `order` number, and
    within each pair the side (which image comes first, i.e. left) is drawn at
    random. Unpaired entries are shuffled in as single items.
    """
    groups: dict[str, list[dict]] = {}
    singles: list[list[dict]] = []
    for e in entries:
        if e.get("pair"):
            groups.setdefault(e["pair"], []).append(e)
        else:
            singles.append([e])
    units = list(groups.values()) + singles
    rng.shuffle(units)
    # Optional editorial order (e.g. hardest pair last): units with an `order`
    # come first in that order; the rest keep their shuffled order after them.
    units.sort(key=lambda u: min(e.get("order", float("inf")) for e in u))
    for unit in units:
        rng.shuffle(unit)  # random side within each pair
    return [e for unit in units for e in unit]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--tasks-json", type=Path, default=Path("data/tasks.json"))
    parser.add_argument("--out-dir", type=Path, default=None)
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()

    out_dir = args.out_dir or Path("assets/vote_images") / f"{args.task_id}_clean"
    entries = json.loads(args.manifest.read_text())
    rng = random.Random(args.seed)
    ordered = _order(entries, rng)

    vote_images = []
    for i, entry in enumerate(ordered, start=1):
        image_id = f"img_{i:02d}"
        dest = out_dir / f"{image_id}.jpg"
        normalise(Path(entry["path"]), dest)
        item = {"id": image_id, "path": dest.as_posix(), "label": entry["label"]}
        if entry.get("pair"):
            item["pair"] = entry["pair"]
        if entry.get("hint"):
            item["hint"] = entry["hint"]
        vote_images.append(item)
        pair = f"[{entry['pair']}] " if entry.get("pair") else ""
        print(f"{image_id}  {pair}{entry['label']:<9}  <- {entry['path']}")

    tasks = json.loads(args.tasks_json.read_text())
    task = next((t for t in tasks if t["id"] == args.task_id), None)
    if task is None:
        raise SystemExit(f"Task {args.task_id!r} not found in {args.tasks_json}")
    task["vote_images"] = vote_images
    args.tasks_json.write_text(json.dumps(tasks, indent=2, ensure_ascii=False) + "\n")
    print(f"Wrote {len(vote_images)} images to {out_dir} and updated {args.tasks_json}")


if __name__ == "__main__":
    main()
