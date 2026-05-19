from pydantic import BaseModel


class Round(BaseModel):
    id: str
    title: str
    description: str
    mode: str
    target_image_path: str | None = None
    input_image_paths: list[str] = []
    is_active: bool = False
    submissions_open: bool = False
    gallery_revealed: bool = False
    prompts_revealed: bool = False
    voting_open: bool = False
    created_at: str = ""
    updated_at: str = ""


class Submission(BaseModel):
    """One generation attempt by a team in a round.

    A team may accumulate several draft rows (one per generate click, up to
    `AppSettings.max_attempts`); exactly one of them ends up with
    `is_chosen=True` when the team picks their favourite. The chosen row is
    what the gallery and CSV export read.
    """

    id: str
    round_id: str
    team_name: str
    prompt: str
    image_path: str | None = None
    status: str
    error_message: str | None = None
    prediction_id: str | None = None
    model_slug: str | None = None
    is_chosen: bool = False
    created_at: str
    updated_at: str


class ModelEntry(BaseModel):
    """An entry in the catalog of selectable Replicate models.

    The catalog is loaded from a JSON file and synced into the `models` table
    on startup. Instructors can toggle `is_enabled` at runtime; the student
    UI only offers enabled entries.
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
