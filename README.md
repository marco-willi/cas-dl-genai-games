# Generative AI CV Classroom Game

An interactive web app for one-day courses on generative AI in computer vision.
Students freely browse a set of tasks and use the Replicate image-generation API
to create images. Task modes:

- **Text to image** (`text2img`, formerly `business`) — free prompting, a business brief, "make it fail", synthetic training data
- **Match** — recreate a target image using text prompting only
- **Edit** — transform a source image with a prompt
- **Compose** — place a cut-out object into a generated scene
- **Explore** — edit your own upload, or one of the task's prepared images, with a text instruction (e.g. *I want a refund!*: manipulate a receipt or a meal, or create a fake receipt from text alone)
- **Vote** — *real vs AI* voting game: students vote on a grid of pre-labelled images; once the instructor reveals the results, everyone sees their score, a leaderboard, the true labels, crowd accuracy and a hint per image (no generation involved)
- **Comparison** — *model bake-off*: write one prompt, fan it out across several models in a single click, and compare the outputs side by side, grouped by round

Each student picks any available task from the sidebar (grouped into sections),
has a fixed budget of generations per task (default 30, configurable via
`GENERATION_BUDGET`, adjustable live by the instructor), and shares their best
result — or a matching pair, where a task asks for two — into that task's public
gallery, where classmates can like it. Models that accept a seed show it, take an
optional fixed seed, and offer a **Re-roll** (same prompt, new seed). An
**Admin** page (instructor passcode) controls a global generation switch, vote
reveals, task availability, gallery moderation, resets and exports; a
**Projector** page shows a gallery or vote results full-screen for the beamer.

---

## Local Setup

**Requirements:** Python 3.14+, [uv](https://docs.astral.sh/uv/)

> The devcontainer (`.devcontainer/`) ships with uv and runs `uv sync`
> automatically on first build — inside it you can skip straight to the `.env` step.

```bash
git clone <repo-url>
cd <repo>

# Install dependencies (creates .venv/, includes the dev group, writes uv.lock)
uv sync

# Copy and fill in environment variables
cp .env.example .env
# edit .env — at minimum set REPLICATE_API_TOKEN, APP_PASSCODE (class passcode)
# and INSTRUCTOR_PASSCODE (admin passcode)

# Run the app
uv run streamlit run app.py
# or: make run
```

The app opens at http://localhost:8501.

> **No API key?** Set `USE_STUB_GENERATION=true` in `.env` to run without
> Replicate. A grey placeholder image is returned for every generation.

---

## Environment Variables

Copy `.env.example` to `.env` and set values before running.

| Variable | Required | Default | Description |
|---|---|---|---|
| `REPLICATE_API_TOKEN` | Yes* | — | Replicate API token. Not needed if `USE_STUB_GENERATION=true`. |
| `APP_PASSCODE` | Yes | `changeme` | Class passcode students enter with their name. Change before classroom use. |
| `INSTRUCTOR_PASSCODE` | Yes | `changeme` | Passcode for the Admin and Projector pages. Change before classroom use. |
| `APP_TITLE` | No | `Generative AI CV Classroom Game` | Browser tab title and app heading. |
| `DEFAULT_REPLICATE_MODEL` | No | — | Fallback Replicate model ref (e.g. `google/nano-banana-2`), only used if `models.json` has no enabled model. |
| `DB_PATH` | No | `data/app.db` | SQLite database path (created automatically). |
| `TASKS_PATH` | No | `data/tasks.json` | Path to task definitions file. |
| `GENERATED_DIR` | No | `generated` | Directory where generated images are saved. |
| `ASSETS_DIR` | No | `assets` | Directory for target images and placeholder. |
| `USE_STUB_GENERATION` | No | `false` | Set to `true` to skip Replicate and return a placeholder image. |
| `GENERATION_BUDGET` | No | `3` | Number of generations each student gets per task. The bundled `.env.example` sets `30` to leave room for the model-comparison task's fan-out rounds. The instructor can override it live on the Admin page. |
| `MODELS_PATH` | No | `data/models.json` | Path to the model catalog. |

Paths inside `tasks.json` (target, input and vote images) are relative to the
directory you run `streamlit run` from (the repo root). `ASSETS_DIR` only
controls where the stub placeholder image and the asset sub-folders live.

> **Local secrets win.** Streamlit exports the top-level keys of
> `.streamlit/secrets.toml` as environment variables, overriding `.env` and your
> shell. To test in stub mode, make sure that file doesn't set
> `USE_STUB_GENERATION = "false"` or a real `REPLICATE_API_TOKEN` you don't want used.

## Theme

The look is configured in `.streamlit/config.toml`, which points `theme.base`
at one of three variants in `.streamlit/themes/`:

| Theme | Look |
|---|---|
| `classroom` (default) | Warm, light, rounded, friendly fonts |
| `studio` | Dark gallery look; images pop, good on a projector |
| `lab` | Clean and technical; keeps the light/dark toggle |

Switch with `make theme THEME=studio` and refresh the browser.

---

## Adding Tasks

Edit `data/tasks.json`. Each task is a JSON object:

```json
{
  "id": "my_task_001",
  "title": "My Task Title",
  "nav_title": "Short title",
  "section": "Text to image",
  "icon": ":material/brush:",
  "description": "Instructions shown to students.",
  "mode": "text2img"
}
```

**Fields** (unknown fields are rejected, so typos fail loudly at startup):

| Field | Values | Notes |
|---|---|---|
| `id` | unique string | Used as a directory name and URL path; keep it slug-safe |
| `title` | string | Shown as the task heading |
| `nav_title` | string (optional) | Short label for the sidebar; defaults to `title` |
| `section` | string (optional) | Sidebar section; sections appear in order of first use. Default `Tasks` |
| `icon` | Material icon (optional) | e.g. `":material/pets:"`; defaults to an icon per mode |
| `description` | string (Markdown) | Shown below the heading |
| `mode` | `"text2img"`, `"match"`, `"edit"`, `"compose"`, `"explore"`, `"vote"`, or `"comparison"` | Controls what reference imagery is shown and whether images are sent to the model. `"business"` is still accepted as an alias of `"text2img"` |
| `target_image_path` | path string or `null` | Required for `match` mode; ignored for the others |
| `gallery_picks` | 1–4 (optional, default 1) | How many results each student may share; they appear side by side in one gallery card. Sharing beyond the limit replaces the student's oldest pick. *Yummy!* uses 2 (two matching menu photos) |
| `input_image_labels` | `{path: label}` (optional) | Friendly names for the prepared images in the source picker (`explore`); default: derived from the file name |
| `allow_text_only` | bool (optional, `explore` only) | Also offer "No image — text only" (text-to-image) next to the prepared images |
| `input_image_paths` | list of path strings | Required for `edit` (exactly 1) and `compose` (≥ 1); optional for `explore` (prepared images students may pick instead of uploading); ignored otherwise |
| `vote_images` | list of `{id, path, label, pair?, hint?}` objects | Required (non-empty) for `vote` mode; rejected for other modes |

Tasks are synced into the database when the app starts and whenever
`tasks.json` changes (picked up on the next click — no restart needed). Admin
availability choices, galleries and votes are preserved.

---

## Edit / Compose / Explore tasks

These task modes feed an input image to the model and require a model marked
with `supports_image_input: true` in `data/models.json` (currently
`openai/gpt-image-2`, `google/nano-banana-2`,
`black-forest-labs/flux-2-klein-4b`, `bytedance/seedream-5-pro`,
`bytedance/seedream-5-lite`, and `black-forest-labs/flux-3-image`).

Replicate models name their image input differently, so each image-capable
model declares it via `image_input_field` (default `image_input`; GPT Image 2
uses `input_images`, the FLUX models `images`). Check a model's API schema on Replicate before adding it — a
wrong field name is silently ignored and the model then generates from the
prompt alone. Models that accept a `seed` input get `"supports_seed": true`.

Uploads in explore mode are limited to 10 MB (`.streamlit/config.toml`),
downscaled to 1536 px and stripped of metadata before being sent to the model.

- **`edit`** — shows the student one source image and asks them to write a
  prompt that transforms it (e.g. relight, change weather, restyle).
- **`compose`** — shows the student a cut-out object and asks them to write a
  prompt for a scene built around that object.
- **`explore`** — the student uploads their own image and edits it with a text
  instruction; the uploaded file is saved alongside the generation under
  `generated/`. Optionally declare `input_image_paths`: students then pick one
  of these prepared images (labelled from the file name, e.g.
  `food_with_bite.jpg` → "Food with bite", or your own names via
  `input_image_labels`) **or** upload their own. With `allow_text_only: true`
  the picker also offers *No image — text only*: plain text-to-image without a
  source (any model, not only image-input ones). Example: the *I want a
  refund!* task — a hot dog, a bitten burger and a receipt to manipulate, or a
  fake receipt from scratch, to compare both routes.

For edit and explore tasks the source image is stored with each generation, so
gallery and projector cards show **Before | After** side by side.

**Setup:**

1. Drop the input file(s) into the matching directory, named after the task id:

   ```
   assets/input_images/edit/<task_id>.jpg
   assets/input_images/compose/<task_id>.png   # transparent PNG works best
   ```

   Keep each file under ~1.5 MB so per-generation uploads stay snappy.

2. Reference them from `data/tasks.json`:

   ```json
   {
     "id": "edit_relight_storefront",
     "title": "Edit: relight a storefront at golden hour",
     "description": "...",
     "mode": "edit",
     "input_image_paths": ["assets/input_images/edit/edit_relight_storefront.jpg"]
   }
   ```

3. Save `tasks.json` (picked up on the next click). The app refuses to load
   the task file until every referenced image exists on disk — the error
   message names the missing path.

The student model dropdown is filtered to image-input-capable models for these
tasks; the first one in `models.json` order (`sort_order`) is preselected —
currently GPT Image 2.

---

## Model catalog

`data/models.json` lists the models students can choose (`id`, `slug`,
`display_name`, `description`, `sort_order`, `is_enabled`,
`supports_image_input`, `image_input_field`, `supports_seed`). Before adding a
model, read its inputs on Replicate (e.g.
`https://replicate.com/<owner>/<name>/llms.txt`): the image-input field name
and whether a `seed` input exists. Edits are picked up within a few seconds.
The first enabled models (by `sort_order`) are the defaults in the model
dropdown and in a new comparison round.

If Replicate discontinues a model, generations fail with *"Version disabled …
This model has been discontinued"* (422): replace or disable it in
`models.json`.

---

## Adding Target Images

1. Place the image in `assets/target_images/`:

   ```
   assets/target_images/my_scene.jpg
   ```

2. Reference it in `data/tasks.json`:

   ```json
   {
     "id": "match_003",
     "mode": "match",
     "target_image_path": "assets/target_images/my_scene.jpg",
     ...
   }
   ```

3. Save `tasks.json` — no restart needed.

Any common image format (JPEG, PNG, WebP) works. Keep images under 2 MB for fast loading.

---

## Vote tasks (Real vs AI game)

A `vote`-mode task shows students a grid of pre-labelled images. Each student
casts one vote per image — **Real** or **AI** — and can change their mind (one
vote per user per image). Until the instructor flips **Reveal results** on the
Admin page, the **Results** tab only shows participation. After the reveal,
voting closes and everyone sees their own score, the images that fooled them,
a top-5 leaderboard, the most deceptive images, crowd accuracy, the true labels
and an optional per-image `hint`. Images that share a `pair` id (a real photo
and an AI recreation of the same scene) are shown side by side as one block.
No image generation, model, or budget is
involved.

**Zooming.** Students can hover an image to zoom in place (the view follows the
mouse) and click or tap it for a full-screen viewer: scroll or pinch to zoom,
drag to pan, double-click to reset, `+` `-` `0` `Esc` keys. A pair opens side by
side, and when both images have the same framing (aspect ratio) their zoom and
pan are linked. The images are not sent through Streamlit: the browser loads
them from Streamlit's static file server (`static/`, enabled by
`enableStaticServing` in `.streamlit/config.toml`) and caches them, so voting
stays fast. The larger zoom version loads on first hover. If static serving is
off or not actually working (Streamlit mounts `static/` only **at startup**: after
first creating the folder or enabling `enableStaticServing`, restart the app),
or an image is not below `static/`, the page falls back to plain images. The component lives in `src/genai_cv_game/ui/zoom.py` + `zoom_image.js`.

**Don't leak the answer through the files.** Real photos and AI images usually
differ in format (JPEG vs PNG), resolution and metadata, which students can see
by opening an image in a new tab. Keep the originals plus labels and hints in a
manifest and let the script normalise them (same JPEG format, 1280 px long
edge, metadata stripped, neutral names, shuffled order; pairs stay together and
get a random left/right side each; an optional `order` per pair in the
manifest fixes the pair sequence, e.g. hardest last) and rewrite the task's
`vote_images`:

```bash
make vote-images   # = scripts/prepare_vote_images.py for spot_the_fake
```

The manifest for the shipped game is
`assets/vote_images/spot_the_fake/manifest.json`; the originals stay untouched
next to it, and the cleaned images go to `static/vote_images/spot_the_fake/`
(`img_NN.jpg` for the page, a larger `img_NN_zoom.jpg` for the viewer). Every
image gets exactly the same long edge (1280 / 2048 px, upscaling smaller ones),
so even the pixel dimensions don't give anything away, and the same JPEG
settings (quality 92 / 95, full colour resolution). AI images only have ~1–2 MP
of real detail, so upscaled they look softer than their real twins when zoomed
— the larger the zoom size, the more so (see REVIEW.md for measurements).
`--zoom-edge` changes the zoom size.
Visible watermarks (e.g. Gemini's ✦) are not removed.

**Setup:**

1. Drop the images into a per-task folder under `assets/vote_images/`:

   ```
   assets/vote_images/<task_id>/img_01.jpg
   assets/vote_images/<task_id>/img_02.png
   assets/vote_images/<task_id>/manifest.json     # labels, pairs, hints
   ```

2. Reference them from `data/tasks.json`, labelling each `real` or `synthetic`:

   ```json
   {
     "id": "spot_the_fake",
     "title": "Real or AI? Spot the fake",
     "description": "For each image, vote real or AI-generated.",
     "mode": "vote",
     "vote_images": [
       { "id": "img_01", "path": "static/vote_images/spot_the_fake/img_01.jpg", "label": "real", "pair": "portrait", "hint": "Look at ..." },
       { "id": "img_02", "path": "static/vote_images/spot_the_fake/img_02.jpg", "label": "synthetic", "pair": "portrait" }
     ]
   }
   ```

   Each `id` must be unique within the task, `label` must be `real` or
   `synthetic`, `hint` (Markdown) and `pair` are optional (a pair must be exactly
   one `real` + one `synthetic` image, listed next to each other; a pair's hints
   are shown once, below both images), and every `path` must exist on
   disk or the task refuses to load.

3. Save `tasks.json` — no restart needed.

Admin resets clear a vote task's cast votes and hide its results again (keeping
the images), and the Export section offers a per-image **vote results CSV**.

---

## Admin Workflow

1. Sign in like a student, open **Admin** (sidebar, *Instructor* section) and
   enter the instructor passcode.
2. **Stats** — participants, generations, failures and average time to image.
3. **Generation API** — toggle the global on/off switch. When off, students
   cannot start new generations (gallery viewing is unaffected).
   **Generation budget** — raise (or lower) the generations per task for
   everyone at once; overrides `GENERATION_BUDGET` until you reset it. Students
   who hit the old limit can continue immediately; nothing is deleted.
4. **Vote games** — reveal the results of a vote task (also closes voting).
5. **Task availability** — toggle which tasks appear in the students' sidebar.
6. **Data resets** — pick a task and reset it (deletes its generations, likes
   and image files, or votes and reveal state), or reset ALL tasks at once.
7. **Export** — pick a task and download its gallery or vote results as CSV.
8. **Danger zone** — delete the entire database and all generated images.

While signed in as admin, every gallery card shows a **Hide** button: it pulls
an inappropriate entry from the gallery and the student can't share it again.
The **Projector** page shows one task's gallery (most liked first) or vote
results, large and without controls, refreshing live.

---

## Student Workflow

1. Open the app URL provided by the instructor and sign in with your name and
   the class passcode. (Reloading the page signs you out — sign in again with
   the same name to get your work back.)
2. Choose a task from the sidebar.
3. Write a **prompt** describing the image you want, pick a model, and click
   **Generate**.
   - For *Text to image* tasks: create an image matching the brief in the description.
   - For *Match* mode: try to recreate the target image shown above the form.
   - For *Edit* / *Compose* mode: transform or build a scene around the input image.
   - For *Explore* mode: upload your own image (or pick one of the task's
     prepared images), then write an instruction to edit it.
   - For *Comparison* mode: write one prompt, pick up to 4 models, and click
     **Generate across N models** — every model runs the same prompt at once and the
     results line up side by side. Judge them on prompt adherence, realism,
     composition, text rendering, object identity, controllability, and usefulness;
     pick a winner and justify it.
4. Each task gives you a budget of generations (default **30**; the instructor
   can raise it). A notice appears while images are created; failed attempts
   can be discarded to free a slot.
5. Click **Show in gallery** on your favourite result to share it. Most tasks
   take one shared result (sharing another replaces it); tasks like *Yummy!*
   take two, shown side by side.
6. The gallery shows every classmate's shared result for the task and refreshes
   automatically. Like the ones you enjoy; the most liked becomes the
   **Class favourite**.
7. For models with a seed: keep the seed fixed while you change the prompt, or
   use **Re-roll** to see what a new seed alone does.

---

## Troubleshooting

**App starts but shows "No tasks are available"**
All tasks may be toggled off on the Admin page (*Task availability*), or the
database is empty. Tasks are synced from `data/tasks.json` on startup and when
the file changes.

**Generation fails with "Replicate API token is not configured"**
Set `REPLICATE_API_TOKEN` in `.env` or set `USE_STUB_GENERATION=true` for offline use.

**Generation fails with "Could not start generation: …"**
The Replicate API returned an error; the message follows. Check your token,
the model slug in `data/models.json`, and your Replicate account credit. A
*"Version disabled"* (422) error means the model was discontinued — replace it
in `models.json` (see *Model catalog*).

**An edit task ignores the source image**
The model's `image_input_field` in `models.json` is probably wrong; Replicate
silently ignores unknown inputs. Check the model's schema on Replicate.

**Target image shows "Target image is not available"**
The file path in `tasks.json` does not match an existing file. Check
`assets/target_images/` and ensure the path matches exactly (case-sensitive on Linux).

**Students see "Image generation is paused by the instructor"**
The global generation switch is off. Enable it on the Admin page.

**Gallery doesn't show new entries**
The gallery auto-refreshes every 5 seconds. Wait a moment or reload the page.

**Pre-commit hooks fail on first run**
Run `uv run pre-commit install` once after cloning. Then `git commit` will
lint and format automatically.

---

## Deployment

See [DEPLOY.md](DEPLOY.md) — a one-day deployment on Streamlit Community Cloud,
including secrets, a pre-class smoke test, export and teardown. Any host that
runs Python 3.14 and exposes port 8501 works the same way; storage is
ephemeral unless you mount a volume.
