import re
import uuid
from datetime import UTC, datetime


def now_utc() -> str:
    return datetime.now(UTC).isoformat()


def new_id() -> str:
    return str(uuid.uuid4())


def parse_utc(ts: str) -> datetime | None:
    """Parse an ISO timestamp written by `now_utc` (naive values treated as UTC)."""
    try:
        dt = datetime.fromisoformat(ts)
    except TypeError, ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def seconds_since(ts: str) -> float:
    dt = parse_utc(ts)
    return 0.0 if dt is None else (datetime.now(UTC) - dt).total_seconds()


def plural(n: int, word: str, suffix: str = "s") -> str:
    """`plural(1, "slot")` -> "1 slot", `plural(3, "slot")` -> "3 slots"."""
    return f"{n} {word}{'' if n == 1 else suffix}"


# Characters with a meaning in Streamlit Markdown: CommonMark punctuation plus
# `$` (LaTeX) and `:` (emoji shortcodes / colour directives like `:red[..]`).
_MD_SPECIAL = re.compile(r"([\\`*_{}\[\]()#+\-.!|<>~$:])")


def md_escape(text: str) -> str:
    """Escape user-provided text so Streamlit renders it literally."""
    return _MD_SPECIAL.sub(r"\\\1", text)


def truncate(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"
