import uuid
from datetime import datetime, timezone


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id() -> str:
    return str(uuid.uuid4())
