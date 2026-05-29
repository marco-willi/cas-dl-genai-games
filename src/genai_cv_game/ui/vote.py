from __future__ import annotations

from pathlib import Path

import streamlit as st

from genai_cv_game.config import AppSettings
from genai_cv_game.db import (
    cast_vote,
    get_user_votes,
    get_vote_images,
    get_vote_tallies,
)
from genai_cv_game.models import Task, VoteImage

# Results auto-refresh so students watch the tally grow live, mirroring the
# gallery fragment. Only this fragment reruns on the timer.
_RESULTS_REFRESH_SECONDS = 5
_GRID_WIDTH = 3
_LABELS = {"real": "Real photo", "synthetic": "AI-generated"}


def render_vote_page(settings: AppSettings, task: Task) -> None:
    """Render a vote-mode task: a Vote tab and a Results tab."""
    tab_vote, tab_results = st.tabs(["Vote", "Results"])

    with tab_vote:
        st.header(task.title)
        st.write(task.description)
        _render_vote_grid(settings, task)

    with tab_results:
        _render_results_fragment(settings, task.id)


# ── Vote tab ─────────────────────────────────────────────────────────────────


def _render_vote_grid(settings: AppSettings, task: Task) -> None:
    user_name = st.session_state["user_name"]
    images = get_vote_images(settings.db_path, task.id)
    if not images:
        st.info("This game has no images configured yet. Check back later.")
        return

    user_votes = get_user_votes(settings.db_path, task.id, user_name)
    voted = sum(1 for img in images if img.id in user_votes)
    st.caption(
        f"You have voted on {voted} / {len(images)} images. "
        "Click **Real** or **AI** under each image — you can change your mind."
    )

    cols = st.columns(_GRID_WIDTH)
    for i, image in enumerate(images):
        with cols[i % _GRID_WIDTH]:
            _render_vote_card(settings, image, user_votes.get(image.id))


def _render_vote_card(
    settings: AppSettings, image: VoteImage, current: str | None
) -> None:
    path = Path(image.image_path)
    if path.exists():
        st.image(str(path), width="stretch")
    else:
        st.markdown("_(image unavailable)_")

    real_col, synth_col = st.columns(2)
    with real_col:
        if st.button(
            "Real",
            key=f"vote_real_{image.id}",
            type="primary" if current == "real" else "secondary",
            width="stretch",
        ):
            _handle_vote(settings, image, "real")
    with synth_col:
        if st.button(
            "AI",
            key=f"vote_synth_{image.id}",
            type="primary" if current == "synthetic" else "secondary",
            width="stretch",
        ):
            _handle_vote(settings, image, "synthetic")

    if current:
        st.caption(f"✓ Your vote: **{_LABELS[current]}**")
    else:
        st.caption("Not voted yet")


def _handle_vote(settings: AppSettings, image: VoteImage, vote: str) -> None:
    user_name = st.session_state["user_name"]
    try:
        cast_vote(settings.db_path, image.task_id, image.id, user_name, vote)
    except ValueError as e:
        st.error(str(e))
        return
    st.rerun()


# ── Results tab ──────────────────────────────────────────────────────────────


@st.fragment(run_every=_RESULTS_REFRESH_SECONDS)
def _render_results_fragment(settings: AppSettings, task_id: str) -> None:
    images = get_vote_images(settings.db_path, task_id)
    if not images:
        st.info("No images configured yet.")
        return

    tallies = get_vote_tallies(settings.db_path, task_id)

    decided = [img for img in images if _majority(tallies[img.id]) is not None]
    correct = [img for img in decided if _majority(tallies[img.id]) == img.label]
    total_votes = sum(t["real"] + t["synthetic"] for t in tallies.values())

    st.caption("Live results — votes update automatically.")
    if decided:
        acc = len(correct) / len(decided)
        st.metric(
            "Crowd accuracy",
            f"{acc:.0%}",
            help=(
                f"On {len(decided)} image(s) with a majority vote, the crowd "
                f"matched the true label {len(correct)} time(s). "
                f"{total_votes} vote(s) cast in total."
            ),
        )
    else:
        st.write("No votes yet. Cast the first one on the Vote tab!")

    cols = st.columns(_GRID_WIDTH)
    for i, image in enumerate(images):
        with cols[i % _GRID_WIDTH]:
            _render_result_card(image, tallies[image.id])


def _render_result_card(image: VoteImage, tally: dict[str, int]) -> None:
    path = Path(image.image_path)
    if path.exists():
        st.image(str(path), width="stretch")
    else:
        st.markdown("_(image unavailable)_")

    real_n = tally["real"]
    synth_n = tally["synthetic"]
    total = real_n + synth_n

    st.markdown(f"Truth: **{_LABELS[image.label]}**")
    if total == 0:
        st.caption("No votes yet.")
        return

    real_pct = real_n / total
    st.write(
        f"Real: {real_n} · AI: {synth_n}  ({total} vote{'s' if total != 1 else ''})"
    )
    st.progress(real_pct, text=f"{real_pct:.0%} voted Real")

    majority = _majority(tally)
    if majority is None:
        st.warning("No consensus (tie).")
    elif majority == image.label:
        st.success("Crowd guessed correctly ✅")
    else:
        st.error("Crowd was fooled ❌")


def _majority(tally: dict[str, int]) -> str | None:
    """Return the winning label, or None when there are no votes or a tie."""
    real_n = tally["real"]
    synth_n = tally["synthetic"]
    if real_n == synth_n:
        return None
    return "real" if real_n > synth_n else "synthetic"
