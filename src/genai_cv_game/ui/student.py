"""Student task page: generate form, results, gallery tab."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import streamlit as st

from genai_cv_game import service
from genai_cv_game.config import AppSettings
from genai_cv_game.db import (
    BudgetReachedError,
    delete_generation,
    is_api_enabled,
    remove_from_gallery,
    submit_to_gallery,
)
from genai_cv_game.model_catalog import find_model, load_enabled_models
from genai_cv_game.models import (
    FIXED_INPUT_MODES,
    IMAGE_INPUT_MODES,
    UPLOAD_INPUT_MODES,
    Generation,
    ModelEntry,
    Task,
)
from genai_cv_game.ui.common import (
    PRIVACY_NOTE,
    asset_image,
    current_user,
    model_caption,
    prompt_caption,
    thumbnail,
)
from genai_cv_game.ui.gallery import render_gallery
from genai_cv_game.ui.vote import render_vote_page
from genai_cv_game.utils import plural, seconds_since

# How often the "still generating" block re-polls the prediction.
_STUDENT_POLL_SECONDS = 3
_MAX_COMPARISON_MODELS = 4
# Results shown directly; older ones fold into an expander.
_RECENT_RESULTS = 6
_SEED_MAX = 2**31 - 1


def render_task_page(settings: AppSettings, task: Task) -> None:
    """Render one task's page.

    Vote tasks get their own Vote/Results layout; every other mode shows the
    generation workspace (Generate + Gallery tabs).
    """
    if task.mode == "vote":
        render_vote_page(settings, task)
        return

    st.header(task.title)
    # on_change="rerun" makes tabs lazy: only the open tab's content runs, so
    # the hidden gallery (and its auto-refresh) costs nothing while generating.
    tab_generate, tab_gallery = st.tabs(
        [":material/brush: Generate", ":material/photo_library: Gallery"],
        key=f"tabs_{task.id}",
        on_change="rerun",
    )
    if tab_generate.open:
        with tab_generate:
            st.markdown(task.description)
            if task.mode == "match":
                _render_target_image(task)
            elif task.mode in FIXED_INPUT_MODES:
                _render_input_images(task)
            _render_user_workspace(task, settings)
    if tab_gallery.open:
        with tab_gallery:
            render_gallery(settings, task)


# ── Reference imagery ────────────────────────────────────────────────────────


def _render_target_image(task: Task) -> None:
    path = Path(task.target_image_path) if task.target_image_path else None
    if not path or not path.exists():
        st.warning("Target image is not available.")
        return
    with st.container(border=True):
        left, right = st.columns([3, 2], vertical_alignment="center")
        left.image(
            asset_image(path) or str(path),
            caption="Target image",
            alt="Target image to recreate",
        )
        right.markdown(
            "**Recreate this using text only.** Don't describe it too generally: "
            "name the subject, composition, style, lighting, camera perspective "
            "and the details that matter."
        )


def _render_input_images(task: Task) -> None:
    available = service.resolve_input_image_paths(task)
    missing = [p for p in task.input_image_paths if not Path(p).exists()]
    if task.mode == "edit":
        caption = "Source image — your prompt edits this."
        tip = (
            "Describe the change. Be specific about what must **stay** (subject, "
            "layout, text) and what should **change** (lighting, style, "
            "background, time of day, weather, …)."
        )
    else:  # compose
        caption = "Object — your prompt builds a scene around it."
        tip = (
            "Describe the scene around the object. Match lighting and perspective "
            "so the result looks coherent; the object stays the visual hero."
        )
    if available:
        with st.container(border=True):
            cols = st.columns([3, 2], vertical_alignment="center")
            with cols[0]:
                for i, p in enumerate(available):
                    st.image(
                        asset_image(p) or str(p),
                        caption=caption if i == 0 else None,
                        alt=caption,
                    )
            cols[1].markdown(tip)
    if missing:
        st.warning(
            f"{plural(len(missing), 'input image')} not available: {', '.join(missing)}"
        )


# ── Workspace: form first, results below ─────────────────────────────────────


@dataclass(frozen=True)
class _CardContext:
    task: Task
    settings: AppSettings
    locked: bool  # a generation is in flight: no gallery changes meanwhile
    remaining: int  # budget left for re-rolls


def _render_user_workspace(task: Task, settings: AppSettings) -> None:
    user_name = current_user()
    generations = service.reconcile_user_generations(settings, task.id, user_name)
    in_flight = any(g.status == "pending" for g in generations)
    budget = service.generation_budget(settings)
    remaining = service.remaining_budget(generations, budget)

    with st.container(border=True):
        if in_flight:
            _render_in_flight_notice(task, user_name, settings)
        elif not is_api_enabled(settings.db_path):
            st.info(
                "Image generation is paused by the instructor.", icon=":material/pause:"
            )
        elif remaining == 0:
            st.warning(
                f"You have used all {budget} generations for this "
                "task. Pick a result to show in the gallery, or discard a failed "
                "attempt to free a slot.",
                icon=":material/hourglass_empty:",
            )
        elif task.mode == "comparison":
            _render_comparison_form(task, generations, remaining, settings)
        else:
            _render_prompt_form(task, generations, remaining, settings)

    if not generations:
        return
    used = service.live_count(generations)
    st.subheader(f"Your results ({used} / {budget})")
    if task.gallery_picks > 1:
        shared = sum(1 for g in generations if g.in_gallery)
        st.caption(
            f":material/photo_library: Shared in the gallery: **{shared} / "
            f"{task.gallery_picks}** — your picks are shown side by side. Sharing "
            "another one replaces your oldest pick."
        )
    ctx = _CardContext(task, settings, locked=in_flight, remaining=remaining)
    if task.mode == "comparison":
        _render_rounds(generations, ctx)
    else:
        _render_results(generations, ctx)


def _render_results(generations: list[Generation], ctx: _CardContext) -> None:
    newest_first = list(reversed(generations))
    recent, older = newest_first[:_RECENT_RESULTS], newest_first[_RECENT_RESULTS:]
    _render_grid(recent, ctx, n_cols=3)
    if older:
        with st.expander(f"Older attempts ({len(older)})", icon=":material/history:"):
            _render_grid(older, ctx, n_cols=4)


def _render_rounds(generations: list[Generation], ctx: _CardContext) -> None:
    rounds = service.group_rounds(generations)
    for i, round_ in enumerate(rounds):
        with st.container(border=True):
            st.markdown(f"**Round {len(rounds) - i}**")
            prompt_caption(round_[0].prompt, key=f"round_prompt_{round_[0].id}")
            _render_grid(round_, ctx, n_cols=_MAX_COMPARISON_MODELS, show_prompt=False)


def _render_grid(
    generations: list[Generation],
    ctx: _CardContext,
    n_cols: int,
    show_prompt: bool = True,
) -> None:
    cols = st.columns(n_cols)
    for i, gen in enumerate(generations):
        with cols[i % n_cols]:
            _render_generation_card(gen, ctx, show_prompt=show_prompt)


# ── Generation card ──────────────────────────────────────────────────────────


def _render_generation_card(
    gen: Generation, ctx: _CardContext, show_prompt: bool = True
) -> None:
    settings = ctx.settings
    with st.container(border=True):
        if gen.status == "completed" and gen.image_path:
            st.image(gen.image_path, width="stretch", alt=gen.prompt[:200])
        elif gen.status == "pending":
            st.info(
                f"Generating… started {int(seconds_since(gen.created_at))} s ago",
                icon=":material/hourglass_top:",
            )
        else:
            st.error(gen.error_message or "Generation failed.", icon=":material/error:")

        model_caption(settings, gen.model_slug, gen.seed)
        if show_prompt:
            prompt_caption(gen.prompt, key=f"prompt_pop_{gen.id}")

        with st.container(horizontal=True, gap="small"):
            if gen.status == "failed":
                if st.button(
                    "Discard", key=f"discard_{gen.id}", icon=":material/delete:"
                ):
                    delete_generation(settings.db_path, gen.id)
                    st.rerun()
                return
            if gen.status != "completed":
                return
            _render_gallery_action(gen, ctx)
            _render_reroll_action(gen, ctx)


def _render_gallery_action(gen: Generation, ctx: _CardContext) -> None:
    db = ctx.settings.db_path
    if gen.hidden:
        st.caption(
            ":material/visibility_off: Hidden from the gallery by the instructor."
        )
    elif gen.in_gallery:
        if st.button(
            "In gallery",
            key=f"remove_{gen.id}",
            icon=":material/check_circle:",
            type="primary",
            disabled=ctx.locked,
            help="Click to remove it from the gallery.",
        ):
            remove_from_gallery(db, gen.id)
            st.rerun()
    elif st.button(
        "Show in gallery",
        key=f"show_{gen.id}",
        icon=":material/photo_library:",
        disabled=ctx.locked,
        help=(
            "Make this your gallery entry for the task (replaces your current one)."
            if ctx.task.gallery_picks == 1
            else f"Add to your {ctx.task.gallery_picks} gallery picks "
            "(replaces your oldest pick when full)."
        ),
    ):
        try:
            submit_to_gallery(db, gen.id, max_entries=ctx.task.gallery_picks)
        except ValueError as e:
            st.error(str(e))
            return
        st.toast("Added to the gallery!", icon=":material/celebration:")
        st.rerun()


def _render_reroll_action(gen: Generation, ctx: _CardContext) -> None:
    """Same prompt and model, new random seed — isolates sampling noise."""
    model = find_model(ctx.settings.models_path, gen.model_slug)
    if (
        model is None
        or not model.supports_seed
        or ctx.task.mode in UPLOAD_INPUT_MODES
        or ctx.task.mode == "comparison"
    ):
        return
    if st.button(
        "Re-roll",
        key=f"reroll_{gen.id}",
        icon=":material/casino:",
        type="tertiary",
        disabled=ctx.locked or ctx.remaining == 0,
        help="Same prompt and model, new random seed. Costs one generation.",
    ):
        _run_and_rerun(
            lambda: service.start_single_generation(
                ctx.settings, ctx.task, current_user(), gen.prompt, model
            )
        )


# ── Prompt form ──────────────────────────────────────────────────────────────


@st.fragment
def _render_prompt_form(
    task: Task, generations: list[Generation], remaining: int, settings: AppSettings
) -> None:
    next_num = service.live_count(generations) + 1
    last = generations[-1] if generations else None

    st.markdown(f"**Generation {next_num} of {service.generation_budget(settings)}**")
    st.caption(
        f"{plural(remaining, 'generation')} left. Tweak the prompt or switch model."
    )

    source = _Source()
    if task.mode in UPLOAD_INPUT_MODES:
        source = _render_source_picker(task)

    model = _render_model_selector(
        task,
        settings,
        next_num,
        last.model_slug if last else None,
        needs_image=not source.text_only,
    )

    _render_prompt_tips()
    prompt = st.text_area(
        "Your prompt",
        value=last.prompt if last else "",
        key=f"prompt_{task.id}_{next_num}",
    )
    seed = _render_seed_input(
        f"seed_{task.id}_{next_num}", visible=bool(model and model.supports_seed)
    )

    disabled = (
        not prompt.strip()
        or (
            model is None
            and not settings.use_stub_generation
            and not settings.default_replicate_model
        )
        or (
            task.mode in FIXED_INPUT_MODES
            and not service.resolve_input_image_paths(task)
        )
        or (task.mode in UPLOAD_INPUT_MODES and not source.chosen)
    )
    if st.button(
        "Generate",
        type="primary",
        icon=":material/auto_awesome:",
        disabled=disabled,
        key=f"gen_{task.id}_{next_num}",
    ):
        _run_and_rerun(
            lambda: service.start_single_generation(
                settings,
                task,
                current_user(),
                prompt.strip(),
                model,
                upload=source.upload,
                prepared_input=source.prepared,
                text_only=source.text_only,
                seed=seed,
            )
        )


_UPLOAD_OWN = "__upload__"
_TEXT_ONLY = "__text_only__"
_THUMB_WIDTH = 170


@dataclass(frozen=True)
class _Source:
    """What the student chose as the image to edit (at most one field is set)."""

    upload: bytes | None = None  # their own uploaded image
    prepared: str | None = None  # path of one of the task's prepared images
    text_only: bool = False  # no source image: plain text-to-image

    @property
    def chosen(self) -> bool:
        return self.upload is not None or self.prepared is not None or self.text_only


def _render_source_picker(task: Task) -> _Source:
    """Choose the image to edit: a prepared image, text only, or an upload.

    Keys are per task (not per generation), so the choice and the uploaded file
    stay put while the student iterates on prompts.
    """
    prepared = [str(p) for p in service.resolve_input_image_paths(task)]
    if prepared:
        labels = {p: service.input_label(p, task.input_image_labels) for p in prepared}
        with st.container(horizontal=True):
            for p in prepared:
                thumbnail(p, _THUMB_WIDTH, caption=labels[p], alt=labels[p])
        if task.allow_text_only:
            labels[_TEXT_ONLY] = "No image — text only"
        labels[_UPLOAD_OWN] = "Upload my own"
        choice = st.segmented_control(
            "Image to edit",
            options=list(labels),
            format_func=labels.__getitem__,
            default=prepared[0],
            required=True,
            key=f"source_{task.id}",
        )
        if choice == _TEXT_ONLY:
            st.caption(
                "No source image: the model creates the picture from your prompt "
                "alone. Describe everything — nothing is carried over from a photo."
            )
            return _Source(text_only=True)
        if choice != _UPLOAD_OWN:
            return _Source(prepared=choice)

    st.caption(f":material/shield: {PRIVACY_NOTE}")
    uploaded = st.file_uploader(
        "Upload an image to edit",
        type=["png", "jpg", "jpeg", "webp"],
        key=f"upload_{task.id}",
        help="Large images are downscaled to 1536 px; metadata is removed.",
    )
    if uploaded is None:
        return _Source()
    thumbnail(
        uploaded.getvalue(),
        320,
        caption="Your image — your prompt will edit this.",
        alt="Your uploaded image",
    )
    return _Source(upload=uploaded.getvalue())


def _render_seed_input(key: str, visible: bool) -> int | None:
    if not visible:
        return None
    value = st.number_input(
        "Seed (optional)",
        min_value=0,
        max_value=_SEED_MAX,
        value=None,
        step=1,
        placeholder="random",
        key=key,
        help=(
            "Same prompt + same seed → same image. Keep the seed fixed to see "
            "what your prompt change does; leave it empty for a random seed."
        ),
    )
    return int(value) if value is not None else None


def _render_model_selector(
    task: Task,
    settings: AppSettings,
    next_num: int,
    preferred_slug: str | None,
    needs_image: bool = True,
) -> ModelEntry | None:
    """Model dropdown. Returns the chosen model, or None (catalog empty).

    Tasks that send a source image only offer image-input models, unless the
    student picked the text-only route (`needs_image=False`).
    """
    wants_image = task.mode in IMAGE_INPUT_MODES and needs_image
    enabled = load_enabled_models(settings.models_path)
    if wants_image:
        enabled = [m for m in enabled if m.supports_image_input]
    if not enabled:
        if wants_image:
            st.error(
                "This task needs an image-input model, but none are enabled. Ask the "
                "instructor to enable one with `supports_image_input: true`."
            )
        elif settings.use_stub_generation or settings.default_replicate_model:
            st.caption("Using the default model.")
        else:
            st.error("No image generation models are enabled. Ask the instructor.")
        return None

    slugs = [m.slug for m in enabled]
    by_slug = {m.slug: m for m in enabled}
    chosen_slug = st.selectbox(
        "Model",
        options=slugs,
        format_func=lambda s: by_slug[s].display_name,
        index=slugs.index(preferred_slug) if preferred_slug in by_slug else 0,
        key=f"model_{task.id}_{next_num}_{'img' if wants_image else 'txt'}",
    )
    chosen = by_slug[chosen_slug]
    if chosen.description:
        st.caption(chosen.description)
    return chosen


# ── Comparison form ──────────────────────────────────────────────────────────


@st.fragment
def _render_comparison_form(
    task: Task, generations: list[Generation], remaining: int, settings: AppSettings
) -> None:
    """One prompt, many models: fan out to each selected model in one click.

    A fragment, so picking models reruns only this form; starting a round
    reruns the whole app (`st.rerun()` defaults to app scope).
    """
    enabled = load_enabled_models(settings.models_path)
    if not enabled:
        st.error(
            "Model comparison needs at least one enabled model. Ask the instructor."
        )
        return

    cap = min(_MAX_COMPARISON_MODELS, remaining)
    st.markdown("**New comparison round**")
    st.caption(
        f"Write one prompt, pick up to {plural(cap, 'model')}, and generate them all "
        f"at once ({plural(remaining, 'generation slot')} left)."
    )
    _render_prompt_tips()
    prompt = st.text_area("Your prompt", key=f"cmp_prompt_{task.id}")

    by_slug = {m.slug: m for m in enabled}
    selected = st.pills(
        "Models to compare",
        options=list(by_slug),
        selection_mode="multi",
        default=list(by_slug)[: min(3, cap)],
        format_func=lambda s: by_slug[s].display_name,
        key=f"cmp_models_{task.id}",
    )
    models = [by_slug[s] for s in selected]
    n = len(models)
    too_many = n > cap
    if too_many:
        st.warning(f"Select at most {plural(cap, 'model')} for this round.")
    seed = _render_seed_input(
        f"cmp_seed_{task.id}", visible=any(m.supports_seed for m in models)
    )

    label = f"Generate across {plural(n, 'model')}" if n else "Generate"
    if st.button(
        label,
        type="primary",
        icon=":material/auto_awesome:",
        disabled=not prompt.strip() or n == 0 or too_many,
        key=f"cmp_gen_{task.id}",
    ):
        created, errors = service.start_comparison_round(
            settings, task, current_user(), prompt.strip(), models, seed=seed
        )
        for err in errors:
            st.warning(err)
        if created:
            st.rerun()


# ── Running a generation ─────────────────────────────────────────────────────


def _run_and_rerun(start: Callable[[], object]) -> None:
    """Call a service start function; show errors, rerun on success."""
    try:
        start()
    except BudgetReachedError as e:
        st.warning(str(e))
        return
    except service.GenerationError as e:
        st.error(str(e))
        return
    st.rerun()


# ── In-flight polling (auto-refresh while pending) ──────────────────────────


@st.fragment(run_every=_STUDENT_POLL_SECONDS)
def _render_in_flight_notice(task: Task, user_name: str, settings: AppSettings) -> None:
    gens = service.reconcile_user_generations(settings, task.id, user_name)
    pending = sum(1 for g in gens if g.status == "pending")
    if pending:
        st.info(
            f"{plural(pending, 'generation')} running. This usually takes 10–60 seconds…",
            icon=":material/hourglass_top:",
        )
        return
    st.rerun(scope="app")


def _render_prompt_tips() -> None:
    with st.expander("Prompt tips", icon=":material/lightbulb:"):
        st.markdown(
            """
            A strong prompt usually names most of these explicitly:

            - **Subject** — what is in the frame (and what is not)
            - **Composition** — placement, framing, perspective
            - **Style** — photographic, illustration, 3D render, painterly, etc.
            - **Lighting** — soft / harsh, direction, time of day
            - **Camera** — lens (e.g. 35 mm, 85 mm), depth of field, angle
            - **Mood & colour palette** — warm/cool, dominant colours
            - **Details that matter** — text on signage, materials, textures

            Iterate: start broad, then add one constraint at a time and re-run.
            If the model supports a seed, keep it fixed while you change the prompt.
            """
        )
