"""Normalise vote-game images so file properties don't leak the answer.

Real photos and AI images usually differ in format (JPEG vs PNG), resolution and
metadata — students can tell them apart by right-clicking. This script reads a
manifest of *original* images, re-encodes every image to the same format, long
edge and quality (metadata stripped), gives them neutral names in a shuffled
order, and rewrites the task's `vote_images` block in `tasks.json`. Every image
is resized to *exactly* the same long edge (smaller ones are upscaled), so not
even the pixel dimensions give anything away. Images
sharing a `pair` value (real + AI version of the same scene) stay adjacent,
with a random side per pair, so the app shows them side by side.

Each image is written twice into `static/vote_images/<task_id>/` (served by
Streamlit's static file server): `img_NN.jpg` for the page and the larger
`img_NN_zoom.jpg`, which the zoom viewer loads on demand. Originals are never
modified.

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

# Page version: shown at ~300-450 px wide, so 1280 px is plenty. Larger would
# make the (true) resolution gap between real photos (4-17 MP) and AI images
# (~1-2 MP, upscaled to match) visible at first glance.
LONG_EDGE = 1280
QUALITY = 92
# Zoom version: loaded on demand by the zoom viewer. 2048 px keeps most of the
# detail of the real photos while the AI images are upscaled <= ~1.7x. At 2400 px
# the AI images are clearly blurrier than their real twins in 5 of 6 pairs (local
# sharpness 0.1-0.5x), which turns "blurry = AI" into a shortcut; at 1600 px the
# viewer runs out of pixels quickly.
ZOOM_EDGE = 2048
ZOOM_QUALITY = 95
# 4:4:4 = full colour resolution (PIL's default 4:2:0 halves it, which shows as
# colour fringing when zoomed). The same settings are used for every image.
SUBSAMPLING = 0


def normalise(
    src: Path,
    dest: Path,
    zoom_dest: Path | None = None,
    long_edge: int = LONG_EDGE,
    zoom_edge: int = ZOOM_EDGE,
) -> None:
    """Write `dest` (and optionally a larger `zoom_dest`) from `src`.

    Both are JPEGs without metadata whose long edge is exactly `long_edge` /
    `zoom_edge` — upscaling smaller sources — so file properties can't tell a
    real photo from an AI image. Upscaled images show less detail when zoomed;
    that is the image's true resolution, not an artefact to hide.
    """
    with Image.open(src) as raw:
        im = ImageOps.exif_transpose(raw).convert("RGB")
    dest.parent.mkdir(parents=True, exist_ok=True)
    for target, edge, quality in (
        (dest, long_edge, QUALITY),
        (zoom_dest, zoom_edge, ZOOM_QUALITY),
    ):
        if target is None:
            continue
        scale = edge / max(im.size)
        size = (round(im.width * scale), round(im.height * scale))
        # No exif/icc passed -> metadata stripped.
        im.resize(size, Image.Resampling.LANCZOS).save(
            target, "JPEG", quality=quality, subsampling=SUBSAMPLING, optimize=True
        )


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
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=None,
        help="default: static/vote_images/<task-id> (must stay below static/)",
    )
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--zoom-edge", type=int, default=ZOOM_EDGE)
    args = parser.parse_args()

    out_dir = args.out_dir or Path("static/vote_images") / args.task_id
    for old in [*out_dir.glob("img_*.jpg")] if out_dir.is_dir() else []:
        old.unlink()  # no stale images from an earlier, longer run
    entries = json.loads(args.manifest.read_text())
    rng = random.Random(args.seed)
    ordered = _order(entries, rng)

    vote_images = []
    for i, entry in enumerate(ordered, start=1):
        image_id = f"img_{i:02d}"
        dest = out_dir / f"{image_id}.jpg"
        normalise(
            Path(entry["path"]),
            dest,
            out_dir / f"{image_id}_zoom.jpg",
            zoom_edge=args.zoom_edge,
        )
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
