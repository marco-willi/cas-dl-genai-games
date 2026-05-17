from pydantic import BaseModel


class Round(BaseModel):
    id: str
    title: str
    description: str
    mode: str
    target_image_path: str | None = None
    is_active: bool = False
    submissions_open: bool = False
    gallery_revealed: bool = False
    prompts_revealed: bool = False
    voting_open: bool = False
    created_at: str = ""
    updated_at: str = ""


class Submission(BaseModel):
    id: str
    round_id: str
    team_name: str
    prompt: str
    image_path: str | None = None
    status: str
    error_message: str | None = None
    prediction_id: str | None = None
    created_at: str
    updated_at: str


class Vote(BaseModel):
    id: str
    round_id: str
    submission_id: str
    voter_name: str
    created_at: str
