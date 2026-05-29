from typing import Literal

from pydantic import BaseModel

VoteLabel = Literal["real", "synthetic"]
VOTE_LABELS: frozenset[str] = frozenset({"real", "synthetic"})


class VoteImage(BaseModel):
    """One pre-labelled image shown in a `vote`-mode task.

    Images are declared inline in `tasks.json` under `vote_images` and synced
    into the `vote_images` table. The `label` is the ground truth revealed only
    on the Results tab.
    """

    id: str
    task_id: str = ""
    image_path: str
    label: VoteLabel
    sort_order: int = 0
    created_at: str = ""
    updated_at: str = ""


class Vote(BaseModel):
    """A single user's real/synthetic guess for one vote image.

    At most one row exists per (image, user); re-voting updates it in place.
    """

    id: str
    task_id: str
    image_id: str
    user_name: str
    vote: VoteLabel
    created_at: str
    updated_at: str


class Task(BaseModel):
    id: str
    title: str
    description: str
    mode: str
    target_image_path: str | None = None
    input_image_paths: list[str] = []
    vote_images: list[VoteImage] = []
    is_available: bool = True
    sort_order: int = 0
    created_at: str = ""
    updated_at: str = ""


class Generation(BaseModel):
    """One generation attempt by a user on a task.

    A user may accumulate up to `AppSettings.generation_budget` non-failed rows
    per task; at most one of them has `in_gallery=True` when the user promotes
    a favourite into the task's public gallery.
    """

    id: str
    task_id: str
    user_name: str
    prompt: str
    image_path: str | None = None
    status: str
    error_message: str | None = None
    prediction_id: str | None = None
    model_slug: str | None = None
    in_gallery: bool = False
    created_at: str
    updated_at: str


class ModelEntry(BaseModel):
    """An entry in the catalog of selectable Replicate models.

    The catalog is loaded from a JSON file. The student UI only offers entries
    with `is_enabled` true.
    """

    id: str
    slug: str
    display_name: str
    description: str | None = None
    is_enabled: bool = True
    supports_image_input: bool = False
    sort_order: int = 0
    created_at: str = ""
    updated_at: str = ""
