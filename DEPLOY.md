# Deployment Guide

This guide covers deploying the app for **a single in-class session**. The
deployment is intentionally short-lived: spin it up before class, share the URL
with students, take it down afterwards.

**Recommended platform:** [Streamlit Community Cloud](https://streamlit.io/cloud).
It is free, deploys directly from GitHub, manages secrets, and is the path
documented by the [Streamlit deploy concepts](https://docs.streamlit.io/deploy/concepts).

---

## Why Streamlit Community Cloud for this use case

| Need | Why Community Cloud fits |
|---|---|
| ~10 concurrent teams | Comfortably within the free-tier resource limits |
| Public URL students can open | Each app gets a `*.streamlit.app` URL |
| Replicate token + instructor passcode | Native secrets UI — no `.env` upload needed |
| Runs for a few hours, then gone | App can be deleted in one click after class |
| Ephemeral generated images | Acceptable: results matter only during the session |

Trade-offs to be aware of:

- The filesystem is **ephemeral**. `data/app.db` and everything under
  `generated/` is wiped on every restart. For a single session this is fine; do
  not rely on it for any record you want to keep beyond class.
- The app sleeps after periods of inactivity. The first request after sleep
  takes ~30 s to wake. Open the URL yourself a minute before class starts.
- Community Cloud apps deployed from a public repo are publicly reachable.
  Anyone with the URL can open the student view. The instructor sidebar is
  protected by `INSTRUCTOR_PASSCODE` — set a strong one (see below).

---

## Prerequisites

- The project is pushed to a **GitHub repository** (public is simplest; private
  works if you connect Streamlit to your GitHub account with repo access).
- A **Streamlit Community Cloud** account: sign in at
  [share.streamlit.io](https://share.streamlit.io) with the GitHub account that
  owns (or has access to) the repo.
- A **Replicate API token** with credit available
  ([replicate.com/account/api-tokens](https://replicate.com/account/api-tokens)).
- A chosen Replicate model reference, e.g. `google/imagen-4-fast`.

---

## Deploy steps

### 1. Push the repo to GitHub

```bash
git push origin main
```

Make sure `.env`, `data/app.db`, and `generated/*` are not committed (they are
already in `.gitignore`).

### 2. Create the app on Streamlit Community Cloud

1. Go to [share.streamlit.io](https://share.streamlit.io) and click **Create app**.
2. Pick **Deploy a public app from GitHub**.
3. Fill in:
   - **Repository:** `<your-org>/<your-repo>`
   - **Branch:** `main`
   - **Main file path:** `app.py`
   - **App URL:** pick a short, memorable slug, e.g. `genai-cv-class`.
4. Click **Advanced settings** → set **Python version** to `3.14` (the project
   requires it; the default is older).
5. Open the **Secrets** tab in Advanced settings (see next step) before
   clicking Deploy.

### 3. Configure secrets

In the **Secrets** field, paste a TOML block. Streamlit makes these available
as environment variables at runtime, which is exactly what the app reads via
`python-dotenv` / `os.environ`.

```toml
REPLICATE_API_TOKEN = "r8_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
INSTRUCTOR_PASSCODE = "pick-something-students-cannot-guess"
DEFAULT_REPLICATE_MODEL = "google/imagen-4-fast"
APP_TITLE = "Generative AI CV Classroom Game"
USE_STUB_GENERATION = "false"
```

Notes:
- Do **not** set `DB_PATH`, `ROUNDS_PATH`, `GENERATED_DIR`, or `ASSETS_DIR` —
  the defaults work and point inside the app's working directory.
- Change `INSTRUCTOR_PASSCODE` from the default — anyone with the URL can try
  to log into the sidebar.
- If you want to test the deployment without spending Replicate credit, set
  `USE_STUB_GENERATION = "true"` first; flip to `"false"` before class.

### 4. Deploy

Click **Deploy**. The first build installs Poetry, resolves dependencies, and
starts the app. This takes 3–5 minutes. Watch the logs in the right-hand
panel; the app is live when you see `You can now view your Streamlit app`.

### 5. Smoke test before class

1. Open the app URL.
2. Confirm the title renders and a round is active.
3. In the sidebar, log in with `INSTRUCTOR_PASSCODE`.
4. Open submissions, submit one test prompt as a "student", confirm an image
   is generated and appears in the gallery.
5. Reset the round so students start clean.

### 6. Share the URL

Send students the app URL (e.g. `https://genai-cv-class.streamlit.app`). They
do **not** need accounts; they just open the link, enter a team name, and submit.

---

## Running the session

- Keep the Streamlit Cloud dashboard open in another tab — you can see live
  logs there if something misbehaves.
- If the app gets stuck, **Reboot app** from the dashboard. Be aware this
  wipes the database; only use it if you are willing to restart the round.
- The instructor controls (open/close submissions, reveal gallery, reveal
  prompts, voting, CSV export) all run in the sidebar — same workflow as local.

---

## Export results

Before tearing the app down, use the **Download submissions CSV** button in
the instructor sidebar for each round you want to keep. The CSV is downloaded
to your local machine, so it survives the app's deletion.

Generated image files live on the Cloud filesystem and **will be lost** when
the app is deleted or restarted. If you want to keep them, screenshot the
gallery or have a teammate save the images during class.

---

## Teardown after class

Because this is a short-lived deployment, delete the app once class is over:

1. Open [share.streamlit.io](https://share.streamlit.io).
2. Click the `⋮` menu next to the app → **Delete app**.
3. Confirm.

This frees the URL slug for reuse and ensures no one can hit the deployment
later. It also stops any further Replicate charges from being possible via
this app.

Optionally rotate the `REPLICATE_API_TOKEN` at
[replicate.com/account/api-tokens](https://replicate.com/account/api-tokens)
once class is finished — the token was exposed only inside Streamlit's secret
store, but rotating is cheap insurance.

---

## Troubleshooting

**Build fails with a Python version error**
The project requires Python 3.14. Set it under *Advanced settings → Python
version* before deploying. If you forgot, edit the app settings and reboot.

**App boots but every generation fails**
Check that `REPLICATE_API_TOKEN` and `DEFAULT_REPLICATE_MODEL` are set in the
Secrets panel and that the Replicate account has credit. Logs in the Cloud
dashboard show the underlying error.

**"No active round" on first load**
The DB is created and rounds are synced from `data/rounds.json` at startup.
If you see this, the sync did not run — reboot the app from the dashboard.

**App is slow to respond when class starts**
It probably went to sleep. Open the URL yourself 1–2 minutes before students
do; the first request wakes it.

**Need to deploy somewhere else**
If Community Cloud is not an option (e.g. private classroom network), the app
is a plain Streamlit + SQLite process. Anywhere that runs Python 3.14 and
exposes port `8501` will work: a single VM with `poetry run streamlit run
app.py`, a small Cloud Run container, etc. Set the same env vars as in the
Secrets block above. The same ephemeral-storage caveats apply unless you mount
a persistent volume.
