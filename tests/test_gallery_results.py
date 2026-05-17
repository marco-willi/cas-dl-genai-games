"""Tests for the pure results-computation helper used by the gallery banner."""

from genai_cv_game.models import Submission
from genai_cv_game.ui.gallery import compute_results


def _sub(sid: str, team: str) -> Submission:
    return Submission(
        id=sid,
        round_id="r1",
        team_name=team,
        prompt="p",
        status="completed",
        created_at="t",
        updated_at="t",
    )


def test_empty_vote_counts_returns_empty():
    assert compute_results({}, []) == []


def test_sorts_by_votes_descending():
    subs = [_sub("a", "Alice"), _sub("b", "Bob"), _sub("c", "Carol")]
    counts = {"a": 1, "b": 3, "c": 2}
    assert compute_results(counts, subs) == [("Bob", 3), ("Carol", 2), ("Alice", 1)]


def test_ties_break_by_team_name():
    """Stable tie-break keeps the bar chart order deterministic."""
    subs = [_sub("a", "Bob"), _sub("b", "Alice")]
    counts = {"a": 2, "b": 2}
    assert compute_results(counts, subs) == [("Alice", 2), ("Bob", 2)]


def test_unknown_submission_id_falls_back_to_id():
    counts = {"orphan": 1}
    assert compute_results(counts, []) == [("orphan", 1)]
