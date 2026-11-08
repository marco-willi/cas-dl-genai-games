"""Vote-mode task ("Real or AI?"): Vote tab + Results tab.

Results stay hidden until the instructor reveals them on the Admin page. After
the reveal, voting is locked and everyone sees their score, the leaderboard,
the true labels, and a hint per image explaining the tell-tale signs.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable

import pandas as pd
import streamlit as st

from genai_cv_game.config import AppSettings
from genai_cv_game.db import (
    cast_vote,
    get_user_votes,
    get_vote_images,
    get_vote_scores,
    get_vote_tallies,
    is_vote_revealed,
)
from genai_cv_game.models import Task, VoteImage
from genai_cv_game.ui.common import asset_image, current_user
from genai_cv_game.utils import md_escape, plural

_RESULTS_REFRESH_SECONDS = 5
_GRID_WIDTH = 3
# Paired images (real + AI version of one scene): pairs per row.
_PAIRS_PER_ROW = 2
_LEADERBOARD_SIZE = 5
_LABELS = {"real": "Real photo", "synthetic": "AI-generated"}


def render_vote_page(settings: AppSettings, task: Task) -> None:
    st.header(task.title)
    tab_vote, tab_results = st.tabs(
        [":material/how_to_vote: Vote", ":material/leaderboard: Results"],
        key=f"tabs_{task.id}",
        on_change="rerun",  # lazy: only the open tab renders
    )
    if tab_vote.open:
        with tab_vote:
            st.markdown(task.description)
            _render_vote_grid(settings, task)
    if tab_results.open:
        with tab_results:
            _render_results_fragment(settings, task.id, current_user())


# ── Vote tab ─────────────────────────────────────────────────────────────────


@st.fragment
def _render_vote_grid(settings: AppSettings, task: Task) -> None:
    """A fragment: a vote click reruns only the grid, not the whole page."""
    user_name = current_user()
    images = get_vote_images(settings.db_path, task.id)
    if not images:
        st.info("This game has no images configured yet. Check back later.")
        return

    revealed = is_vote_revealed(settings.db_path, task.id)
    user_votes = get_user_votes(settings.db_path, task.id, user_name)
    voted = sum(1 for img in images if img.id in user_votes)
    if revealed:
        st.success(
            "The results are out — open the **Results** tab. Voting is closed.",
            icon=":material/celebration:",
        )
    else:
        st.progress(
            voted / len(images),
            text=f"You voted on {voted} / {len(images)} images. You can change your mind "
            "until the instructor reveals the results.",
        )

    _render_layout(
        images,
        lambda image: _render_vote_card(
            settings, image, user_votes.get(image.id), locked=revealed
        ),
    )


def _units(images: list[VoteImage]) -> list[list[VoteImage]]:
    """Group images into display units: adjacent images sharing a `pair` id
    form one unit (their left/right order comes from tasks.json), every other
    image is a unit of its own."""
    units: list[list[VoteImage]] = []
    for img in images:
        if img.pair and units and units[-1][0].pair == img.pair:
            units[-1].append(img)
        else:
            units.append([img])
    return units


def _render_layout(
    images: list[VoteImage],
    render_card: Callable[[VoteImage], None],
    footer: Callable[[list[VoteImage]], None] | None = None,
) -> None:
    """Pairs side by side (two pairs per row); plain grid if nothing is paired.

    `footer`, if given, is rendered once below each pair (e.g. the pair's hint).
    """
    units = _units(images)
    if all(len(u) == 1 for u in units):
        cols = st.columns(_GRID_WIDTH)
        for i, image in enumerate(images):
            with cols[i % _GRID_WIDTH]:
                render_card(image)
        return
    outer = st.columns(_PAIRS_PER_ROW)
    for n, unit in enumerate(units):
        with outer[n % _PAIRS_PER_ROW], st.container(border=True):
            st.markdown(f"**Pair {n + 1}**" if len(unit) > 1 else "**Single image**")
            for col, image in zip(st.columns(len(unit)), unit, strict=True):
                with col:
                    render_card(image)
            if footer is not None:
                footer(unit)


def _render_vote_card(
    settings: AppSettings, image: VoteImage, current: str | None, locked: bool
) -> None:
    with st.container(border=True):
        _image(image)
        with st.container(horizontal=True, gap="small"):
            for label, text, icon in (
                ("real", "Real", ":material/photo_camera:"),
                ("synthetic", "AI", ":material/smart_toy:"),
            ):
                # A callback records the vote *before* the (fragment) rerun, so
                # one click = one rerun with the new state already visible.
                st.button(
                    text,
                    key=f"vote_{label}_{image.id}",
                    icon=icon,
                    type="primary" if current == label else "secondary",
                    width="stretch",
                    disabled=locked,
                    on_click=_cast_vote,
                    args=(settings, image, label),
                )


def _cast_vote(settings: AppSettings, image: VoteImage, label: str) -> None:
    try:
        cast_vote(settings.db_path, image.task_id, image.id, current_user(), label)
    except ValueError as e:  # e.g. the image was removed meanwhile
        st.toast(str(e), icon=":material/error:")


# ── Results tab ──────────────────────────────────────────────────────────────


@st.fragment(run_every=_RESULTS_REFRESH_SECONDS)
def _render_results_fragment(
    settings: AppSettings, task_id: str, user_name: str | None
) -> None:
    render_vote_results(settings, task_id, user_name)


def render_vote_results(
    settings: AppSettings, task_id: str, user_name: str | None
) -> None:
    """Results view. `user_name=None` is the projector view (no personal score)."""
    images = get_vote_images(settings.db_path, task_id)
    if not images:
        st.info("No images configured yet.")
        return
    tallies = get_vote_tallies(settings.db_path, task_id)
    scores = get_vote_scores(settings.db_path, task_id)

    if not is_vote_revealed(settings.db_path, task_id):
        _render_waiting(images, tallies, n_voters=len(scores))
        return

    my_votes = get_user_votes(settings.db_path, task_id, user_name) if user_name else {}
    with st.container(horizontal=True):
        if user_name:
            correct = sum(1 for img in images if my_votes.get(img.id) == img.label)
            st.metric(
                "Your score",
                f"{correct} / {len(images)}",
                border=True,
                help=f"You voted on {len(my_votes)} of {len(images)} images.",
            )
        _crowd_accuracy_metric(images, tallies)
        st.metric("Players", len(scores), border=True)

    left, right = st.columns(2)
    with left:
        _render_leaderboard(scores, n_images=len(images), me=user_name)
    with right:
        _render_deception_chart(images, tallies)
    _render_score_histogram(scores, n_images=len(images))

    if user_name:
        fooled = [
            img
            for img in images
            if img.id in my_votes and my_votes[img.id] != img.label
        ]
        if fooled:
            st.caption("Fooled you: " + ", ".join(f"`{img.id}`" for img in fooled))

    st.subheader("All images")
    _render_layout(
        images,
        lambda image: _render_result_card(
            image, tallies[image.id], my_votes.get(image.id)
        ),
        footer=_render_hint,
    )


def _render_waiting(
    images: list[VoteImage], tallies: dict[str, dict[str, int]], n_voters: int
) -> None:
    total_votes = sum(t["real"] + t["synthetic"] for t in tallies.values())
    st.info(
        "The true labels are revealed by the instructor once everyone has voted.",
        title="Results are hidden for now",
        icon=":material/visibility_off:",
    )
    with st.container(horizontal=True):
        st.metric("Players so far", n_voters, border=True)
        st.metric("Votes cast", total_votes, border=True)
        complete = n_voters * len(images)
        st.metric(
            "Completion",
            f"{total_votes / complete:.0%}" if complete else "—",
            border=True,
            help="Votes cast ÷ (players × images).",
        )


def _crowd_accuracy_metric(
    images: list[VoteImage], tallies: dict[str, dict[str, int]]
) -> None:
    decided = [img for img in images if _majority(tallies[img.id]) is not None]
    correct = [img for img in decided if _majority(tallies[img.id]) == img.label]
    st.metric(
        "Crowd accuracy",
        f"{len(correct) / len(decided):.0%}" if decided else "—",
        border=True,
        help=(
            f"On {plural(len(decided), 'image')} with a majority vote, the majority "
            f"was right {plural(len(correct), 'time')}."
        ),
    )


def _render_leaderboard(scores: list, n_images: int, me: str | None) -> None:
    st.markdown("**:material/trophy: Leaderboard**")
    if not scores:
        st.caption("No votes yet.")
        return
    lines = []
    for rank, s in enumerate(scores[:_LEADERBOARD_SIZE], start=1):
        name = md_escape(s.user_name)
        if me and s.user_name.lower() == me.lower():
            name = f"**{name} (you)**"
        lines.append(f"{rank}. {name} — {s.correct} / {n_images}")
    st.markdown("\n".join(lines))


def _render_deception_chart(
    images: list[VoteImage], tallies: dict[str, dict[str, int]]
) -> None:
    rows = []
    for img in images:
        t = tallies[img.id]
        total = t["real"] + t["synthetic"]
        if total:
            wrong = t["synthetic"] if img.label == "real" else t["real"]
            rows.append({"image": img.id, "fooled (%)": round(100 * wrong / total)})
    st.markdown("**:material/psychology_alt: Most deceptive images**")
    if not rows:
        st.caption("No votes yet.")
        return
    st.bar_chart(
        pd.DataFrame(rows),
        x="image",
        y="fooled (%)",
        horizontal=True,
        sort="-fooled (%)",
        height=300,
        alt="Share of votes that guessed wrong, per image",
    )


def _render_score_histogram(scores: list, n_images: int) -> None:
    if len(scores) < 2:
        return
    counts = Counter(s.correct for s in scores)
    df = pd.DataFrame(
        {
            "correct answers": list(range(n_images + 1)),
            "players": [counts.get(k, 0) for k in range(n_images + 1)],
        }
    )
    with st.expander("Score distribution", icon=":material/bar_chart:"):
        st.bar_chart(
            df,
            x="correct answers",
            y="players",
            sort=False,
            height=220,
            alt="Number of players per score",
        )


def _render_result_card(
    image: VoteImage, tally: dict[str, int], my_vote: str | None
) -> None:
    with st.container(border=True):
        _image(image)
        is_ai = image.label == "synthetic"
        with st.container(horizontal=True, vertical_alignment="center"):
            st.badge(
                _LABELS[image.label],
                icon=":material/smart_toy:" if is_ai else ":material/photo_camera:",
                color="violet" if is_ai else "green",
            )
            if my_vote:
                ok = my_vote == image.label
                st.badge(
                    "You were right" if ok else "Fooled you",
                    icon=":material/check:" if ok else ":material/close:",
                    color="green" if ok else "red",
                )
        total = tally["real"] + tally["synthetic"]
        if total:
            real_pct = tally["real"] / total
            st.progress(
                real_pct,
                text=f"{real_pct:.0%} voted Real · {plural(total, 'vote')}",
            )
            majority = _majority(tally)
            if majority is None:
                st.caption("No consensus (tie).")
            elif majority == image.label:
                st.caption(":material/check_circle: The crowd got it right.")
            else:
                st.caption(":red[:material/cancel: The crowd was fooled.]")
        else:
            st.caption("No votes.")
        if not image.pair:  # paired images get one shared hint below the pair
            _render_hint([image])


def _render_hint(unit: list[VoteImage]) -> None:
    """One "What gives it away?" expander for an image or a pair."""
    hints = [img.hint for img in unit if img.hint]
    if hints:
        with st.expander("What gives it away?", icon=":material/lightbulb:"):
            st.markdown("\n\n".join(hints))


def _image(image: VoteImage) -> None:
    data = asset_image(image.image_path)
    if data is not None:
        st.image(data, width="stretch", caption=image.id, alt=f"Vote image {image.id}")
    else:
        st.caption("_(image unavailable)_")


def _majority(tally: dict[str, int]) -> str | None:
    """Return the winning label, or None when there are no votes or a tie."""
    real_n, synth_n = tally["real"], tally["synthetic"]
    if real_n == synth_n:
        return None
    return "real" if real_n > synth_n else "synthetic"
