# Generative AI CV Classroom Game

An interactive web app for one-day courses on generative AI in computer vision.
Students freely browse a set of tasks and use the Replicate image-generation API
to create images. Task modes:

- **Business** — create a hero image for a fictional business brief
- **Match** — recreate a target image using text prompting only
- **Edit** — transform a source image with a prompt
- **Compose** — place a cut-out object into a generated scene
- **Explore** — upload your own image and edit it with a text instruction (open-ended)
- **Vote** — *real vs AI* voting game: students vote on a grid of pre-labelled images and a Results tab reveals the tallies, true labels, and crowd accuracy (no generation involved)
- **Comparison** — *model bake-off*: write one prompt, fan it out across several models in a single click, and compare the outputs side by side

Each student picks any available task, has a fixed budget of generations per
task (default 30, configurable via `GENERATION_BUDGET`), and may share one result
into that task's public gallery. An admin panel
(password-protected sidebar) controls a global generation on/off switch, which
tasks are available, and gallery resets.

---

## Local Setup

**Requirements:** Python 3.14+, [Poetry](https://python-poetry.org/)

```bash
git clone <repo-url>
cd <repo>

# Install dependencies
poetry install --with dev

# Copy and fill in environment variables
cp .env.example .env
# edit .env — at minimum set REPLICATE_API_TOKEN and INSTRUCTOR_PASSCODE (admin passcode)

# Run the app
poetry run streamlit run app.py
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
| `INSTRUCTOR_PASSCODE` | Yes | `changeme` | Passcode for the admin sidebar. Change before classroom use. |
| `APP_TITLE` | No | `Generative AI CV Classroom Game` | Browser tab title and app heading. |
| `DEFAULT_REPLICATE_MODEL` | Yes* | — | Replicate model ref, e.g. `google/imagen-4-fast`. Not needed in stub mode. |
| `DB_PATH` | No | `data/app.db` | SQLite database path (created automatically). |
| `TASKS_PATH` | No | `data/tasks.json` | Path to task definitions file. |
| `GENERATED_DIR` | No | `generated` | Directory where generated images are saved. |
| `ASSETS_DIR` | No | `assets` | Directory for target images and placeholder. |
| `USE_STUB_GENERATION` | No | `false` | Set to `true` to skip Replicate and return a placeholder image. |
| `GENERATION_BUDGET` | No | `3` | Number of generations each student gets per task. The bundled `.env.example` sets `30` to leave room for the model-comparison task's fan-out rounds. |

---

## Adding Tasks

Edit `data/tasks.json`. Each task is a JSON object:

```json
{
  "id": "my_task_001",
  "title": "My Task Title",
  "description": "Instructions shown to students.",
  "mode": "business",
  "target_image_path": null
}
```

**Fields:**

| Field | Values | Notes |
|---|---|---|
| `id` | unique string | Used as a directory name; keep it slug-safe |
| `title` | string | Shown as the task heading and in the task picker |
| `description` | string | Shown below the heading |
| `mode` | `"business"`, `"match"`, `"edit"`, `"compose"`, `"explore"`, `"vote"`, or `"comparison"` | Controls what reference imagery is shown and whether images are sent to the model |
| `target_image_path` | path string or `null` | Required for `match` mode; ignored for the others |
| `input_image_paths` | list of path strings | Required for `edit` (exactly 1) and `compose` (≥ 1); ignored for `business` / `match` / `explore` |
| `vote_images` | list of `{id, path, label}` objects | Required (non-empty) for `vote` mode; rejected for other modes |

Tasks are synced into the database on every app start. Adding or renaming a task
takes effect on the next restart; admin availability choices are preserved.

---

## Edit / Compose / Explore tasks

These task modes feed an input image to the model and require a model marked
with `supports_image_input: true` in `data/models.json` (currently
`google/nano-banana-2`, `black-forest-labs/flux-2-flex`, and
`bytedance/seedream-5-lite`).

- **`edit`** — shows the student one source image and asks them to write a
  prompt that transforms it (e.g. relight, change weather, restyle).
- **`compose`** — shows the student a cut-out object and asks them to write a
  prompt for a scene built around that object.
- **`explore`** — the student uploads their own image and edits it with a text
  instruction. No `input_image_paths` are declared (the upload is the source);
  the uploaded file is saved alongside the generation under `generated/`.

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

3. Restart the app. The task will refuse to load until every referenced file
   exists on disk — the error message names the missing path.

The student model dropdown is filtered to image-input-capable models for these
tasks, and `nano-banana-2` is the recommended default.

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

3. Restart the app.

Any common image format (JPEG, PNG, WebP) works. Keep images under 2 MB for fast loading.

---

## Vote tasks (Real vs AI game)

A `vote`-mode task shows students a grid of pre-labelled images. Each student
casts one vote per image — **Real** or **AI** — and can change their mind until
they leave the page (one vote per user per image). The **Results** tab updates
live with per-image tallies, reveals the true label, flags whether the crowd's
majority guessed correctly, and shows an overall crowd-accuracy metric. No image
generation, model, or budget is involved.

**Setup:**

1. Drop the images into a per-task folder under `assets/vote_images/`:

   ```
   assets/vote_images/<task_id>/img_01.jpg
   assets/vote_images/<task_id>/img_02.png
   ```

2. Reference them from `data/tasks.json`, labelling each `real` or `synthetic`:

   ```json
   {
     "id": "spot_the_fake",
     "title": "Real or AI? Spot the fake",
     "description": "For each image, vote real or AI-generated.",
     "mode": "vote",
     "vote_images": [
       { "id": "img_01", "path": "assets/vote_images/spot_the_fake/img_01.png", "label": "real" },
       { "id": "img_02", "path": "assets/vote_images/spot_the_fake/img_02.png", "label": "synthetic" }
     ]
   }
   ```

   Each `id` must be unique within the task, `label` must be `real` or
   `synthetic`, and every `path` must exist on disk or the task refuses to load.

3. Restart the app. The shipped `spot_the_fake` task uses placeholder images —
   replace them with your own real photos and AI generations.

Admin resets clear a vote task's cast votes (keeping the images), and the Export
section offers a per-image **vote results CSV** for vote tasks.

---

## Admin Workflow

1. Open the app and enter the admin passcode in the sidebar.
2. **Generation API** — toggle the global on/off switch. When off, students
   cannot start new generations (gallery viewing is unaffected).
3. **Task availability** — toggle which tasks appear in the student task picker.
4. **Gallery resets** — pick a task and reset it (deletes its generations and
   image files, freeing students' budgets), or reset ALL galleries at once.
5. **Export** — pick a task and download its gallery as CSV.
6. **Danger zone** — delete the entire database and all generated images.

---

## Student Workflow

1. Open the app URL provided by the instructor and sign in with your name.
2. Choose a task from the **Choose a task** dropdown.
3. Write a **prompt** describing the image you want, pick a model, and click
   **Generate**.
   - For *Business* mode: create an image matching the brief in the description.
   - For *Match* mode: try to recreate the target image shown above the form.
   - For *Edit* / *Compose* mode: transform or build a scene around the input image.
   - For *Explore* mode: upload your own image, then write an instruction to edit it.
   - For *Comparison* mode: write one prompt, pick up to 4 models, and click
     **Generate across N models** — every model runs the same prompt at once and the
     results line up side by side. Judge them on prompt adherence, realism,
     composition, text rendering, object identity, controllability, and usefulness;
     pick a winner and justify it.
4. Most tasks give you a budget of generations per task (default **30**). A spinner
   appears while each image is created; failed attempts can be discarded to free a slot.
5. Click **Show in gallery** on your favourite result to share it. Only one of
   your results per task can be in the gallery at a time.
6. The gallery shows every classmate's shared result for the task and refreshes
   automatically.

---

## Troubleshooting

**App starts but shows "No tasks are available"**
All tasks may be toggled off in the admin panel, or the database is empty.
Tasks are synced from `data/tasks.json` on startup; check availability in the
admin sidebar.

**Generation fails with "Replicate API token is not configured"**
Set `REPLICATE_API_TOKEN` in `.env` or set `USE_STUB_GENERATION=true` for offline use.

**Generation fails with "Image generation failed"**
The Replicate API returned an error. Check your token, model name, and Replicate account
quota. Try a different model ref in `DEFAULT_REPLICATE_MODEL`.

**Target image shows "Target image is not available"**
The file path in `tasks.json` does not match an existing file. Check
`assets/target_images/` and ensure the path matches exactly (case-sensitive on Linux).

**Students see "Image generation is currently paused"**
The global generation API switch is off. Enable it in the admin sidebar.

**Gallery doesn't show new entries**
The gallery auto-refreshes every 5 seconds. Wait a moment or reload the page.

**Pre-commit hooks fail on first run**
Run `poetry run pre-commit install` once after cloning. Then `git commit` will
lint and format automatically.

---

## Deployment (Optional)

### Streamlit Community Cloud

1. Push the repo to GitHub.
2. Go to [share.streamlit.io](https://share.streamlit.io) and connect the repo.
3. Set secrets in the Streamlit dashboard (equivalent to `.env` values).
4. Note: generated images are stored on an ephemeral filesystem — they will not
   persist across restarts. For persistent storage, mount a volume or use cloud storage.

### Google Cloud Run

Build and deploy a container:

```bash
gcloud run deploy genai-cv-game \
  --source . \
  --port 8501 \
  --set-env-vars REPLICATE_API_TOKEN=...,INSTRUCTOR_PASSCODE=...
```

The filesystem is ephemeral on Cloud Run. For persistent generated images, configure
a Cloud Storage bucket and update `GENERATED_DIR` accordingly (not included in MVP).
