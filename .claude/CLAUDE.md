# Generative AI CV Classroom Game

Streamlit + SQLite app for a **one-day course** on generative AI in computer
vision. Students sign in with a name + class passcode, work through tasks
(generate / edit / compose / compare images via the Replicate API, or play a
"real vs AI" voting game), share their best result(s) per task to a live gallery
and like classmates' entries. Deployed for a single session on Streamlit
Community Cloud, then deleted (see `DEPLOY.md`). Filesystem and DB are ephemeral
by design.

## Commands

```bash
uv sync                      # install (dev group included by default)
make run                     # uv run streamlit run app.py  → http://localhost:8501
make test                    # pytest (~30 s), coverage gate 80% (ui/ excluded)
make lint / make format      # ruff
uv run mypy src app.py       # type check (clean; slow here, ~1–2 min)
make theme THEME=studio      # switch theme: classroom | studio | lab
make vote-images             # re-encode + shuffle vote images from their manifest
uv run python scripts/make_refund_inputs.py   # redraw the refund task's input images
```

Python 3.14+, uv. `ruff format` may emit 3.14-only syntax (e.g. `except A, B:`).
Known, deliberate ruff findings: 4× BLE001 (catch-all around Replicate/network
calls) and 1× TRY004 — leave them.

Config via `.env` (loaded in `app.py`) or Streamlit secrets.
Never read or print `.streamlit/secrets.toml` or `.env`.

## Layout

```
app.py                         entry: .env → settings → _bootstrap (cached) → login → st.navigation
                               (Home, task sections from tasks.json, Instructor: Admin + Projector)
src/genai_cv_game/
  config.py                    AppSettings (pydantic) from env vars; MAX_GENERATION_BUDGET
  models.py                    Mode/GenerationStatus Literals, mode capability sets,
                               Task, Generation, VoteImage, ModelEntry (validate from sqlite rows)
  db.py                        all SQLite access; schema + column migrations; reactions,
                               vote scores/reveal, class stats, app_settings (budget, reveals)
  tasks.py                     TaskDefinition (pydantic) validation of tasks.json, sync into DB
  model_catalog.py             models.json loader (cached; mtime re-checked every few s)
  generation.py                Replicate start (by model name or pinned version) / poll; stub mode
  service.py                   UI-free workflow: start single/comparison, reconcile pending,
                               effective budget, seed picking, round grouping, input labels
  storage.py                   paths, image download, upload normalisation, CSV export
  utils.py                     time helpers, plural(), md_escape(), truncate()
  ui/common.py                 admin auth, mode icons, asset_image() cache, escaped captions
  ui/home.py                   landing page
  ui/student.py                task page: form first (fragment), source picker, results
                               newest first, comparison rounds
  ui/gallery.py                gallery fragment: one card per student (picks side by side),
                               Before | After, likes, favourite, admin Hide; projector variant
  ui/vote.py                   vote page; pairs side by side; results hidden until reveal;
                               scores, leaderboard, per-pair hints
  ui/admin.py                  stats, API switch, budget, vote reveal, availability, resets,
                               export, wipe
  ui/projector.py              admin-only big-screen gallery / vote results
data/tasks.json                task definitions (order = sidebar order)
data/models.json               model catalog
assets/vote_images/<task>/     original vote images + manifest.json (labels, pair, order, hints)
assets/vote_images/<task>_clean/  normalised images actually used by tasks.json
assets/input_images/refund/    receipt + placeholder food image (scripts/make_refund_inputs.py)
scripts/prepare_vote_images.py normalise/shuffle vote images, rewrite tasks.json
.streamlit/config.toml         upload limit + theme.base → .streamlit/themes/*.toml
tests/                         pytest; test_service.py / test_features.py cover newer features
```

Docs: `README.md` (setup, task/model authoring, workflows), `DEPLOY.md`
(one-day Streamlit Cloud deployment), `REVIEW.md` (review findings, decisions,
change log), `IDEAS.md` (prompt ideas). `.claude/plans/archive/` holds old
implementation plans that describe **earlier** designs (e.g. rounds) — don't
treat them as current.

## Domain concepts

- **Modes** (`models.Mode`): `text2img` (alias `business`), `match`, `edit` (1 fixed
  input image), `compose` (≥1 fixed cut-out), `explore` (student upload, or pick one of
  the task's `input_image_paths` — see `ui/student._render_source_picker`),
  `comparison` (one prompt → up to 4 models, shared `batch_id` = one round),
  `vote` (no generation). Capability sets (`FIXED_INPUT_MODES`, …) live in `models.py`.
- **Generation lifecycle**: row `pending` → prediction id stored → polled by
  `service.reconcile_generation` (fragment every 3 s) → `completed` / `failed`;
  pending > 180 s → failed. One status vocabulary everywhere.
- **Replicate inputs**: image input key per model (`image_input_field`); `seed` only for
  `supports_seed` models — the app always sends an explicit seed so it can show it.
- **Budget**: non-failed generations per (task, user name). Effective value via
  `service.generation_budget()`: admin override (`app_settings` key `generation_budget`)
  else `GENERATION_BUDGET`. Never read `settings.generation_budget` directly in the UI.
- **Before/after**: `generations.input_image_path` records the edited source (fixed input,
  prepared choice or saved upload); single-pick gallery cards show Before | After.
- **Gallery**: up to `tasks.gallery_picks` (default 1) `in_gallery` rows per (task, user),
  enforced in `db.submit_to_gallery` (oldest pick replaced); cards group a user's picks.
  `hidden` rows were pulled by the admin and can't be re-shared; likes in `reactions`
  (per image, not on own entries).
- **Vote pairs**: `VoteImage.pair` groups a real photo with its AI recreation; adjacent in
  tasks.json (left/right = order), rendered side by side by `ui/vote._render_layout`;
  a pair's hint is shown once below it.
- **Vote reveal**: `app_settings` key `reveal:<task_id>`; reveal closes voting.
- **Identity**: user name only, case-insensitive. No accounts (deliberate — see REVIEW.md S3).

## Conventions

- DB access only through `db.py`; one short-lived connection per call.
- Business logic in `service.py` (no `st.*`); `ui/` only renders and calls it.
- Escape any user-provided text rendered as Markdown with `md_escape`.
- Performance (every click reruns the script, so keep the per-rerun path cheap):
  - tasks.json → DB sync runs once per process (`_bootstrap` in `app.py`, `st.cache_resource`
    keyed on tasks.json mtime + DB existence); never call it per rerun.
  - Tabs are lazy (`st.tabs(..., key=..., on_change="rerun")` + `if tab.open:`).
  - Interactive forms and the vote grid are `@st.fragment`s; buttons that only change
    fragment state use `on_click` callbacks (no extra `st.rerun()`).
  - Static asset images go through `ui.common.asset_image` (bytes cached in memory);
    generated images are not cached (memory).
  - `@st.fragment(run_every=...)` for anything that auto-refreshes.
- Schema changes: new columns go in `_SCHEMA` **and** `_ADDED_COLUMNS` (`db.py`); index
  changes must also handle existing DBs (e.g. `DROP INDEX IF EXISTS` in `_SCHEMA`).
- Adding a task: edit `data/tasks.json` (fields documented in README); unknown fields
  are rejected, referenced files must exist. Picked up without restart.
- Adding/replacing a model: check its inputs first via
  `https://replicate.com/<owner>/<name>/llms.txt` (WebFetch on replicate.com is
  pre-allowed) — set `image_input_field` (wrong names are silently ignored) and
  `supports_seed` only if a `seed` input exists. Don't guess.
- Record user-facing decisions and larger changes in `REVIEW.md`.

## Verifying in the running app

Never run verification against the real repo directory: `.streamlit/secrets.toml`
would override stub mode and could make paid Replicate calls. Instead:

```bash
SP=<scratchpad>; mkdir -p $SP/apprun
tar --exclude='data/app.db*' -cf - app.py data assets .streamlit/config.toml .streamlit/themes \
  | tar -xf - -C $SP/apprun          # then confirm: no $SP/apprun/.streamlit/secrets.toml, no .env
cd $SP/apprun && env -u REPLICATE_API_TOKEN USE_STUB_GENERATION=true APP_PASSCODE=class \
  INSTRUCTOR_PASSCODE=teach uv run --project /workspace streamlit run app.py \
  --server.headless=true --server.address=127.0.0.1 --server.port=8766 --server.enableAgentApi=true
```

Drive it via `POST /_stcore/agent/interact` (see the `developing-with-streamlit` skill):
- The first request after start can exceed 30 s (cold start) → resend with `session_id`.
- Selectbox/pills values are the **display labels**, not slugs; the Home page's
  `url_path` is `""`; disabled buttons must be enabled by a previous request.
- The package is imported from `/workspace/src`: restart the server after editing it.
- Check the server log for warnings/tracebacks; stop the server when done.
