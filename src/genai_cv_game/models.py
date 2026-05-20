from pydantic import BaseModel


class Task(BaseModel):
    id: str
    title: str
    description: str
    mode: str
    target_image_path: str | None = None
    input_image_paths: list[str] = []
    is_available: bool = True
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
