# Generative AI CV Classroom Game

An interactive multi-team web app for one-day courses on generative AI in computer vision.
Students compete in two game modes using the Replicate image-generation API:

- **Business** — create a hero image for a fictional business brief
- **Match** — recreate a target image using text prompting only

Up to ~10 teams submit prompts, generate images, and vote on results. The instructor
controls pacing from a password-protected sidebar.

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
# edit .env — at minimum set REPLICATE_API_TOKEN and INSTRUCTOR_PASSCODE

# Run the app
poetry run streamlit run app.py
# or: make run
```

The app opens at http://localhost:8501.

> **No API key?** Set `USE_STUB_GENERATION=true` in `.env` to run without
> Replicate. A grey placeholder image is returned for every submission.

---

## Environment Variables

Copy `.env.example` to `.env` and set values before running.

| Variable | Required | Default | Description |
|---|---|---|---|
| `REPLICATE_API_TOKEN` | Yes* | — | Replicate API token. Not needed if `USE_STUB_GENERATION=true`. |
| `INSTRUCTOR_PASSCODE` | Yes | `changeme` | Passcode for the instructor sidebar. Change before classroom use. |
| `APP_TITLE` | No | `Generative AI CV Classroom Game` | Browser tab title and app heading. |
| `DEFAULT_REPLICATE_MODEL` | Yes* | — | Replicate model ref, e.g. `google/imagen-4-fast`. Not needed in stub mode. |
| `DB_PATH` | No | `data/app.db` | SQLite database path (created automatically). |
| `ROUNDS_PATH` | No | `data/rounds.json` | Path to round definitions file. |
| `GENERATED_DIR` | No | `generated` | Directory where generated images are saved. |
| `ASSETS_DIR` | No | `assets` | Directory for target images and placeholder. |
| `USE_STUB_GENERATION` | No | `false` | Set to `true` to skip Replicate and return a placeholder image. |

---

## Adding Rounds

Edit `data/rounds.json`. Each round is a JSON object:

```json
{
  "id": "my_round_001",
  "title": "My Round Title",
  "description": "Instructions shown to students.",
  "mode": "business",
  "target_image_path": null
}
```

**Fields:**

| Field | Values | Notes |
|---|---|---|
| `id` | unique string | Used as a directory name; keep it slug-safe |
| `title` | string | Shown as the round heading |
| `description` | string | Shown below the heading |
| `mode` | `"business"` or `"match"` | Controls whether a target image is shown |
| `target_image_path` | path string or `null` | Required for `match` mode; ignored for `business` |

Rounds are synced into the database on every app start. Adding or renaming a round
takes effect on the next restart; instructor state (active, open, revealed) is preserved.

---

## Adding Target Images

1. Place the image in `assets/target_images/`:

   ```
   assets/target_images/my_scene.jpg
   ```

2. Reference it in `data/rounds.json`:

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

## Instructor Workflow

1. Open the app and enter the instructor passcode in the sidebar.
2. Select the active round from the **Active Round** dropdown.
3. Toggle **Submissions open** → students can now submit prompts.
4. Watch the **Submissions** counter in the sidebar until all teams have submitted.
5. Toggle **Submissions open** off to close the round.
6. Toggle **Gallery revealed** → all generated images appear on screen.
7. Toggle **Prompts revealed** → the prompt used by each team is shown under their image.
8. Toggle **Voting open** → students can vote for their favourite image.
9. Toggle **Voting open** off to close voting; vote counts remain visible.
10. Click **Download submissions CSV** to export results.
11. To run another round: select the next round, check the **Reset** confirmation, click **Reset**, then repeat from step 3.

---

## Student Workflow

1. Open the app URL provided by the instructor.
2. Wait for the instructor to open submissions — a form appears when the round is active.
3. Enter your **team name** and write a **prompt** describing the image you want.
   - For *Business* mode: create an image matching the brief in the description.
   - For *Match* mode: try to recreate the target image shown above the form.
     Include subject, composition, style, lighting, and camera perspective.
4. Click **Generate**. A spinner appears while the image is being created.
5. Your generated image is shown when complete.
6. When the instructor reveals the gallery, all teams' images appear.
7. When voting opens, enter your team name and click **Vote** on your favourite image.

---

## Troubleshooting

**App starts but shows "No active round"**
The database may be empty or all rounds were reset. Restart the app — rounds are
synced from `data/rounds.json` on startup and the first round is activated automatically.

**Generation fails with "Replicate API token is not configured"**
Set `REPLICATE_API_TOKEN` in `.env` or set `USE_STUB_GENERATION=true` for offline use.

**Generation fails with "Image generation failed"**
The Replicate API returned an error. Check your token, model name, and Replicate account
quota. Try a different model ref in `DEFAULT_REPLICATE_MODEL`.

**Target image shows "Target image is not available"**
The file path in `rounds.json` does not match an existing file. Check
`assets/target_images/` and ensure the path matches exactly (case-sensitive on Linux).

**Gallery doesn't show new submissions**
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
