# Generative AI CV Classroom Game

A web app for a one-day course on generative AI in computer vision. Students sign
in with a name and a class passcode, work through tasks with the Replicate
image-generation API, share their best result to a live gallery and like their
classmates' entries.

## Task types

- **Text to image:** free prompting, a business brief, "make it fail"
- **Match:** recreate a target image with text only
- **Edit / Compose:** transform a source image, or build a scene around a cut-out
- **Explore:** edit your own upload or a prepared image (e.g. the refund task)
- **Vote:** "real vs AI" game with scores and a leaderboard after the reveal
- **Comparison:** one prompt, several models, results side by side

Each student has a generation budget per task (instructor-adjustable). Models
with a seed support take an optional fixed seed and offer a **Re-roll**. The
instructor gets an **Admin** page (switches, budget, vote reveal, moderation,
resets, export) and a **Projector** page for the beamer.

## Quick start

Requires Python 3.14+ and [uv](https://docs.astral.sh/uv/). The devcontainer
already runs `uv sync`.

```bash
uv sync
cp .env.example .env   # set REPLICATE_API_TOKEN, APP_PASSCODE, INSTRUCTOR_PASSCODE
make run               # http://localhost:8501
```

No API key? Set `USE_STUB_GENERATION=true` in `.env`: every generation returns a
grey placeholder.

Other commands: `make test`, `make lint`, `make format`,
`make theme THEME=studio|classroom|lab`, `make vote-images`.

## Documentation

- [docs/DEVELOP.md](docs/DEVELOP.md): environment variables, themes, adding
  tasks / models / images, vote games, admin and student workflow, troubleshooting
- [docs/DEPLOY.md](docs/DEPLOY.md): one-day deployment on Streamlit Community Cloud
- [.claude/CLAUDE.md](.claude/CLAUDE.md): architecture and conventions for developers
