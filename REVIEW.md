# App Review — Generative AI CV Classroom Game

*Reviewed 2026-11-07, at commit `638047a` plus uncommitted working-tree changes. All 129 tests pass.*

The app is meant to run for **one day** for a class of students, then be deleted.
The review is weighted to fit that. It doesn't ask for hardened authentication or
persistence. It does take seriously anything that could cost money, spoil the
lesson, or embarrass someone in front of the class during the session.

Severity: 🔴 high · 🟠 medium · 🟡 low · 💡 idea.
"Verify" means I couldn't confirm the item from the code alone.

Status tags, added after the owner reviewed this report:
✅ done · 📌 accepted, to do · ⏸️ won't do / resolved elsewhere.

---

## 0. Top priorities before the next session

| # | Item | Area | Effort |
|---|---|---|---|
| 1 | ✅ Stop the vote game giving away its answers (format, resolution, order, reveal toggle) | Didactic | S |
| 2 | ⏸️ ~~Add a global spend cap~~ — covered by the spending limit on the Replicate account | Security/cost | — |
| 3 | ✅ Let the admin hide a single gallery entry | Security/moderation | S |
| 4 | ✅ Put the prompt form above the generation history, newest first | UI | S |
| 5 | ✅ Personal score, leaderboard and reveal toggle in the vote game | Fun | S |
| 6 | ✅ Image-input field per model (FLUX 2 Flex needed `input_images`) | Correctness | S |
| 7 | ✅ Group comparison results by round | UI/Didactic | M |

---

## 1. Security & cost (one-day deployment)

The model of who can do what is simple. Anyone with the URL and the class passcode
can sign in under **any** name, and a name is the whole identity. For one day in a
classroom that is acceptable. The risks that remain are **money**, **content shown
to the class**, and **students tampering with each other's work**.

### ⏸️ S1. The budget is per name, so total spend has no ceiling (resolved elsewhere)
`create_generation` ([db.py:218-265](src/genai_cv_game/db.py#L218-L265)) counts
generations per `(task, user_name)`, so signing in under a new name gives a
fresh budget. **Resolution:** the hard spending limit is set on the Replicate
account, so there is a ceiling outside the app. No change to the app is needed.

### ✅ S2. The admin can't remove one inappropriate gallery entry (implemented)
The provider's own safety filters make this unlikely, but the only tool used
to be **Reset this task**, which deleted everyone's work.

**Implemented:**
- New `generations.hidden` column. The schema migration
  `_migrate_generations_hidden` adds it to an existing `app.db`.
- New `hide_from_gallery()` in `db.py`. It clears `in_gallery` and sets
  `hidden=1`. The generation itself is kept.
- `submit_to_gallery()` now refuses hidden generations, so the student can't
  simply share the image again.
- Gallery cards show a **Hide** button only when
  `st.session_state["admin_authenticated"]` is set. Sign in on the Admin page
  first, then open any task's Gallery tab.
- The student's own card shows "Hidden from the gallery by the instructor."
  instead of the share buttons.
- The admin page has a short caption pointing to the feature.
- 4 new tests in `tests/test_generations.py` cover hiding, the block on
  re-sharing, siblings that can still be shared, and the migration. Total:
  133 passing.

To undo a hide by hand: `UPDATE generations SET hidden=0 WHERE id=...`. There is
no button for this, on purpose.

### ⏸️ S3. Students can act as each other (won't do)
Signing in with a classmate's name gives access to their generations and votes.
**Decision:** don't implement claim tokens. Sign-in has to survive a page
refresh, and a student who gets locked out of their own name is a worse
classroom problem than occasional mischief.

### ✅ S4. Uploads: no size limit, and privacy isn't explained (implemented)

**Status ✅:** `server.maxUploadSize = 10` in `.streamlit/config.toml`; uploads are re-encoded by `storage.save_uploaded_input_image` (EXIF orientation applied, ≤1536 px, metadata incl. GPS dropped, PNG only when transparent). Privacy note on the sign-in page, the home page and above the uploader.
- Explore mode accepts uploads up to Streamlit's default 200 MB
  ([student.py:255-259](src/genai_cv_game/ui/student.py#L255-L259)), saves them
  as they are, and forwards them to Replicate.
  **Fix:** set `server.maxUploadSize = 10` in `.streamlit/config.toml`, and
  downscale to about 1536 px with Pillow before saving and uploading. Uploads
  also get faster.
- Students may upload photos of themselves or of friends. Those go to a
  third-party API (Replicate and the model provider) and sit on the Streamlit
  Cloud disk for the day.
  **Fix:** add one line of explanation on the sign-in page and above the
  uploader ("images are sent to an external AI provider; don't upload photos of
  other people without consent"). This is a good teaching moment as well (see D7).

### ✅ S5. User text is rendered as Markdown (implemented)

**Status ✅:** `utils.md_escape` escapes Markdown, `$` (LaTeX) and `:` (emoji/colour directives); used for names, prompts and model names. Long prompts are truncated with the full text in a popover (`st.text`).
Prompts and names go through `st.caption` / `st.markdown`
([gallery.py:67-72](src/genai_cv_game/ui/gallery.py#L67-L72),
[app.py:80](app.py#L80), [student.py:189](src/genai_cv_game/ui/student.py#L189)).
HTML is escaped, so this is not an XSS hole. Markdown still renders, though: a
name like `# HUGE` turns into a heading, and prompts can contain links or images.
**Fix:** escape the text, or render prompts with `st.text`, or inside a code
span or `st.code`.

### ⏸️ S6. Smaller items (ignored, kept for the record)
- **Budget race:** the SELECT-count and the INSERT in `create_generation` aren't
  inside one explicit transaction. Python's `sqlite3` begins one only at the
  INSERT. A double-click or two open tabs can go one over the budget. Use
  `conn.execute("BEGIN IMMEDIATE")` at the top.
- **Admin passcode:** it is compared on every rerun and nothing slows down
  repeated guesses ([admin.py:29-37](src/genai_cv_game/ui/admin.py#L29-L37)).
  That is fine for one day with a strong passcode. If you like, add
  `hmac.compare_digest` and a counter in session state that locks out after
  five wrong attempts.
- **Raw error text reaches students** (`st.error(f"Could not start generation: {e}")`,
  [student.py:402](src/genai_cv_game/ui/student.py#L402)). This is acceptable,
  and arguably useful for debugging in class. The Replicate token is not
  included in these messages.
- **Polling volume:** every pending generation is polled by both the main render
  and the 3-second fragment, and a new `replicate.Client` is built each time
  ([generation.py:115](src/genai_cv_game/generation.py#L115)). With 30 students
  running 4-model comparisons, that is about 40 GETs every 3 seconds, which is
  well within Replicate's limits. No action is needed. Just keep it in mind if
  the class grows.
- **Teardown:** DEPLOY.md already covers deleting the app and rotating the
  token. That's good, keep it.

---

## 2. Correctness risks to verify

### ✅ C1. `image_input` is hard-coded for every image-input model

**Status ✅ (confirmed bug, fixed):** Replicate's schema for `black-forest-labs/flux-2-flex` uses `input_images`; Nano Banana 2 and Seedream 5 Lite use `image_input`. New `ModelEntry.image_input_field` (set in `models.json`) is used to build the payload.
[generation.py:71-73](src/genai_cv_game/generation.py#L71-L73) always sends the
source images as `image_input`. Replicate models don't share one input schema.
Nano Banana and Seedream use `image_input`, but FLUX 2 models may expect a
different key (e.g. `input_images`). If the key is wrong, Replicate usually
**ignores it without an error**. The model then does plain text-to-image, and
students think editing "doesn't work".

**Verify:** run the edit task once per image-capable model with stub mode off,
and check that the output actually resembles the source.
**Fix:** add an optional `image_input_field` (and `image_input_is_list`) to
`models.json` / `ModelEntry`, and use it when building the payload.

### ✅ C2. Resolving the version for official models

**Status ✅:** predictions are created with `client.predictions.create(model="owner/name")`; an `owner/name:version` slug still pins a version. `_resolve_version` is gone (one API call less per generation).
`_resolve_version` ([generation.py:152](src/genai_cv_game/generation.py#L152))
calls `models.get(...).latest_version`. For Replicate "official" models
(Imagen, FLUX Pro, …) predictions are normally created through the model
endpoint, and `latest_version` may be missing in some cases. If this already
works for every model in `models.json`, ignore it. Otherwise, switch to
`client.models.predictions.create(model="owner/name", input=...)`, which also
saves one API call per generation.

### ⏸️ C3. Smaller items

**Status ⏸️:** ignored by decision (the `sync_vote_images` transaction got fixed anyway as part of Q5).
- `download_image` always saves as `.png` whatever the content type
  ([storage.py:19-26](src/genai_cv_game/storage.py#L19-L26), [storage.py:67](src/genai_cv_game/storage.py#L67)).
  This is harmless in browsers, but CSV exports and downloads will carry the
  wrong extensions.
- `sync_vote_images` deletes and then upserts over separate connections
  ([db.py:443-460](src/genai_cv_game/db.py#L443-L460)). It isn't atomic, but it
  only runs at startup.

---

## 3. UI & visual appeal

Today it is a clean Streamlit app with the default look. It works, but it looks
like an internal tool rather than a "game".

### ✅ U1. The prompt form is pushed below a growing history

**Status ✅:** form (or status message) first in a bordered container; results below, newest first; the 6 most recent shown, older ones in an *Older attempts* expander.
In `_render_user_workspace`
([student.py:134-159](src/genai_cv_game/ui/student.py#L134-L159)) every
generation card is drawn **before** the prompt form, oldest first. With a
budget of 30, students have to scroll past up to 10 rows of images to reach the
prompt box. The newest result also lands at the bottom right.

**Fix:** put the form first. Below it, show the latest generation large, then
the earlier ones newest first, possibly inside an `st.expander("Earlier
attempts")` or capped at the last 6 with "show all".

### ✅ U2. Comparison results are one flat grid

**Status ✅:** new `generations.batch_id`; each comparison click is one round (`service.group_rounds`), rendered as a bordered block with the prompt and one column per model, newest round first. Model choice uses pills.
Comparison generations go into the same grid of up to 4 columns, ordered by
time ([student.py:133-137](src/genai_cv_game/ui/student.py#L133-L137)). After a
couple of rounds with different model counts, or after discarding a failed one,
columns stop lining up with rounds. The side-by-side comparison, which is the
point of the task, is lost.

**Fix:** group by `(prompt, created_at batch)`. Render each round as a
container with the prompt as its header and one column per model, newest round
first.

### ✅ U3. Navigation and identity

**Status ✅:** `nav_title`, `section`, `icon` in `tasks.json`; sidebar sections Warm-up / Text to image / Synthetic data / Image editing / Evaluate / Instructor; new Home page with page links. Admin stays visible (in the *Instructor* section).
- Long task titles crowd the sidebar ("Synthetic training data: camera trap of
  a rare serval"). Add a short `nav_title` field to `tasks.json` and use
  `st.Page(..., title=short, icon=":material/...:")`.
- Group pages into sections with `st.navigation` dicts, e.g.
  **Warm-up** (vote), **Text-to-image** (free, pizzeria, match, make-it-fail,
  serval), **Editing** (edit, compose, explore, serval conditioned),
  **Evaluate** (comparison).
- Add a **Home / Today** page: the day's agenda, how budgets work, the privacy
  note (S4), and a link to the current task.
- The Admin page appears in every student's sidebar. That is harmless, but you
  could show it only after `?admin=1` or after admin sign-in.

### ✅ U4. Theme and polish

**Status ✅:** three theme variants in `.streamlit/themes/` (`classroom` default, `studio` dark, `lab` dual light/dark), switch with `make theme THEME=…`. Plus: redesigned sign-in, pending card with elapsed time, prompt truncation + popover, match target shown once above the gallery, admin stats strip (participants, generations, failed, avg. time to image), most-deceptive-images chart. Material icons throughout.
- Add `.streamlit/config.toml` with a `[theme]` block (primary colour, base
  font, rounded corners). It costs nothing and changes the feel immediately.
- The sign-in page is bare. Add a hero line, a sample image, and "Today you'll
  learn to…".
- Pending cards show only "⏳ _generating…_"
  ([student.py:182-183](src/genai_cv_game/ui/student.py#L182-L183)), so the
  layout jumps when the image arrives. Use a fixed-ratio placeholder, or the
  stub image greyed out, and show elapsed seconds.
- Full prompts under every card make cards very tall. Truncate to about 120
  characters and put the full text in `st.popover`.
- Match gallery: the target image is repeated in every card
  ([gallery.py:82-91](src/genai_cv_game/ui/gallery.py#L82-L91)). Show it once
  above the grid, and use the space for larger results.
- Admin page: "Admin access granted." stays on screen permanently. Replace it
  with a small **live stats** strip: active names, generations used vs. cap,
  failures, and how long the average generation takes.
- Vote results: add a small bar chart sorted by "% fooled" so the most
  deceptive image stands out. That is your debrief slide.

### ✅ U5. Projector / presenter mode

**Status ✅:** *Projector* page (admin only): pick a task; shows its gallery in 2 large columns sorted by likes, or the vote results, live-refreshing.
Add an admin-only page that shows one task's gallery or the vote results in
full screen with big images and no controls, for the beamer during the debrief.

---

## 4. Didactic content & "fun"

**Strengths:** the task sequence is well chosen. It moves from detection (vote),
to free play, to an applied brief (pizzeria), to control (match), to limits
(make it fail), to applied CV (synthetic serval training data, with and without
conditioning), to editing and composition, to structured evaluation
(comparison). Admin availability toggles already let you unlock tasks one by
one. The prompt tips and comparison criteria are concrete. Doing the serval
task with and without conditioning is a strong pairing.

### ✅ D1. The vote game can be solved without looking at the image content

**Status ✅:** `scripts/prepare_vote_images.py` (`make vote-images`) re-encodes all images to JPEG q85, 1280 px long edge, no metadata, neutral names `img_01…12` into `static/vote_images/spot_the_fake/` (since the zoom feature; originally `assets/…_clean/`), and rewrites `tasks.json`. Originals and a `manifest.json` (labels, `pair`, hints) stay in `spot_the_fake/`. *Follow-up:* the 6 real/AI twins are shown **side by side as pairs** (`pair` field, validated: one real + one synthetic, adjacent); pair order is set in the manifest (`order`; the near-impossible hat-colour edit comes last) and the side is random per pair (current file: real left in 3 pairs, right in 3). Hints were rewritten by the instructor and are shown once per pair. ⚠️ Still visible: aspect ratios differ (two AI images are very wide) and **the Gemini street image (now img_10, Pair 5) carries Gemini's ✦ watermark** in the bottom-right corner — crop or replace it if you don't want that tell.
I inspected `assets/vote_images/spot_the_fake/`:

| | Format | Resolution | Size |
|---|---|---|---|
| All 6 **real** | JPEG | 1920–5184 px wide (up to 16 MP) | 0.7–2.7 MB |
| All 6 **synthetic** | PNG | 821–1916 px, about 1–1.6 MP | 2–3 MB |

The order in `tasks.json` also **strictly alternates** real, AI, real, AI, …

Right-clicking an image ("open image in new tab") shows `.png` vs `.jpg` and
the pixel size. Once one student finds the pattern, the game is spoiled for the
whole class. The real photos are also needlessly heavy: about 25 MB per student
for the page.

**Fix:**
- Re-encode all 12 images to the **same format** (JPEG q≈85), downscale to the
  same long edge (e.g. 1280 px), and strip metadata. A short script in
  `scripts/` with Pillow is enough. Crop to a few shared aspect ratios if
  possible.
- Shuffle the order: by hand in JSON, or a seeded shuffle per task.
- Keep the source filenames out of the deployed repo. Rename to `img_01.jpg`, …
  (the filenames include "ChatGPT Image …").

### ✅ D2. The Results tab shows the answers from the first second

**Status ✅:** per-task reveal toggle on the Admin page (`app_settings` key `reveal:<task_id>`). Before: Results shows only players, votes and completion. Revealing closes voting; task reset hides results again.
The Results tab ([vote.py:105-167](src/genai_cv_game/ui/vote.py#L105-L167)) is
visible before voting and shows "Truth: **AI-generated**" for every image.
Curious students will click it first.

**Fix:** add an admin toggle `reveal_<task_id>`, stored in `app_settings`.
Before reveal, Results shows only "N students have voted" and a progress bar.
After reveal, it shows the truths, tallies and accuracy. This turns the reveal
into a **shared classroom moment**.

### ✅ D3. The vote game has no personal score

**Status ✅:** after reveal: *Your score* metric, "Fooled you" list and per-card badges, top-5 leaderboard, score histogram, crowd accuracy, most-deceptive chart. Confidence slider not done.
The only score shown is crowd accuracy. Students want to know *how they* did.

**Fix (fun):**
- After reveal: "You got **9 / 12**". Show which ones fooled you.
- A **class leaderboard** (top 5) and a histogram of scores.
- Optionally, a confidence slider per vote (50–100%) to discuss calibration:
  "people were 90% sure and still wrong".
- After reveal, a "What gave it away?" caption per image (hands, text,
  reflections, lighting, too-perfect skin, noise patterns). Add it as an
  optional `hint` field on `vote_images`.

### ✅ D4. Generation tasks have no feedback loop or competition

**Status ✅ (reactions) / 📋 backlog (rest):** one like per student per entry (not on own), counts on the button, *Class favourite* badge on the most-liked entry, projector sorted by likes. Task-specific awards, match scoring and timed rounds → backlog.
Generating and sharing to a gallery is engaging, but nothing *ends* a task.

**Ideas, cheapest first:**
- **Gallery reactions:** one 👍 per student per entry, and a "Class favourite"
  badge. It is one extra table, similar to `votes`.
- **Task-specific awards voted in the gallery:** *Closest match* (match),
  *Most convincing training sample* (serval), *Most spectacular fail* (make it
  fail), *Best campaign* (pizzeria).
- **Match scoring:** show an automatic similarity score (CLIP or DINO embedding
  cosine between target and result) next to each gallery entry. This is good
  didactically: it shows that "similar to a model" ≠ "similar to a human". It
  needs an embedding model, either a Replicate CLIP model or a local
  `open_clip`, which adds weight. The peer-voted "Closest match" is the
  low-tech version.
- **Timed challenge rounds**, driven by the admin: "5 minutes, best pizzeria
  visual wins".

### 💡 D5. Comparison: make the evaluation structured and shared

**Status 💡:** kept as an idea — a dedicated task for systematic rating. (Rounds are now grouped and seeds shared across seed-capable models, which this would build on.)
The task lists seven criteria but collects nothing, and the gallery accepts only
**one image**, so the comparison itself can't be shared.

**Fix:**
- Per round, a small form: pick a winner and rate 1–5 on 2–3 criteria (adherence,
  realism, text rendering).
- Aggregate into a **class model leaderboard** on the admin or projector page.
  This makes "which model is best *for what*" a data-driven discussion.
- Show **latency per model**, which can be derived from `created_at` →
  `updated_at` on completion, and optionally an approximate **cost per image**
  in `models.json`. Trade-offs then become part of the evaluation.
- Let the gallery share a whole round, not one image.

### ✅ D6. Show what is random and what the prompt controls

**Status ✅ (where the model supports it):** `supports_seed` in `models.json` (FLUX 2 Flex, FLUX 1.1 Pro per Replicate's schema). The app always sends an explicit seed (random unless given) and shows it on every card; optional seed input; **Re-roll** = same prompt + model, new seed. Comparison rounds share one seed. Imagen/Nano Banana/Seedream expose no seed.
Students can't tell whether a change came from their prompt edit or from
random sampling. There is no seed control or seed display.

**Fix:** pass and display a `seed` where the model supports it, and add a
"🎲 Re-roll (same prompt, new seed)" button. One short task, "Same prompt, 4
seeds", teaches stochasticity better than any slide.

### ⏸️ D7. Reflection and responsible-use moments

**Status ⏸️:** ignored for now (only the privacy note from S4 was added).
- An optional "What did you change and why?" note per generation, shown in the
  gallery. It turns trial-and-error into explicit hypothesis testing, which
  matches the exercise style used elsewhere in the course.
- For the serval tasks: show 2–3 **real** camera-trap reference frames next to
  the brief, so "realistic" has a concrete anchor. Add a debrief question:
  "Would you train on these? What distribution shift do they introduce?"
- Label all gallery images as AI-generated, and use the uploads (S4) to
  discuss consent and provenance. This is small, and it fits a CV ethics
  discussion.

### ✅ D8. Task content

**Status ✅ (hints):** a hint per vote image (shown after reveal; each AI image is a recreation of one of the real photos, so the hints point to the twin), a list of classic failure modes in *Make it fail*, edit-task wording fixed. The text-rendering task from `IDEAS.md` was not added.
- `IDEAS.md` already has two good prompts (the giant violin with text
  rendering; the brim-full wine glass). They could become a **"Text rendering"**
  task and a **"Known failure modes"** hint list in *Make it fail*. Seeding
  "Make it fail" with 2–3 well-known failures (clock showing a specific time,
  left-handed writer, full wine glass) helps students who get stuck.
- The edit task description has a typo-level issue: "Keep the architecture,
  signage text, but remove the garbage" → "Keep the architecture and signage
  text, but remove the rubbish bags."

---

## 5. Code structure & clarity

**Strengths:** the layering is sensible (config → models → db → domain → ui).
Pydantic models are used, and the docstrings explain *why* rather than *what*.
The start/poll design for generation survives a rerun or refresh. The partial
unique index enforces the one-gallery-entry rule in the database itself. There
is a small schema migration, stub mode for working offline, and 129 tests with
a coverage gate. Overall this is easy to read.

### ✅ Q1. Mode handling is scattered and inconsistent

**Status ✅:** `Mode` Literal + `FIXED_INPUT_MODES`/`UPLOAD_INPUT_MODES`/`IMAGE_INPUT_MODES` in `models.py`; `business` renamed to `text2img` (alias still accepted in JSON and old DBs).
- `mode` is a bare `str` ([models.py](src/genai_cv_game/models.py)).
- Mode sets are defined twice, and they disagree. In
  [tasks.py:12](src/genai_cv_game/tasks.py#L12) `_IMAGE_INPUT_MODES = {"edit",
  "compose"}` is **unused**, while
  [student.py:32-38](src/genai_cv_game/ui/student.py#L32-L38) defines it as
  `{"edit","compose","explore"}`, plus three more sets.
- `business` is used for tasks that aren't business briefs (free exploration,
  make it fail, serval). It really means "text-to-image".

**Fix:** in `models.py`, add `Mode = Literal[...]` or a `StrEnum`, plus one
small capability table, e.g. `MODE_CAPS = {Mode.EDIT: Caps(image_input="fixed"), ...}`.
Rename `business` → `text2img` and keep `business` as an alias while you
migrate.

### ✅ Q2. Orchestration logic lives in the UI module

**Status ✅:** new `service.py` (start single/comparison, reconcile, budget, seed, rounds) with its own tests; `ui/student.py` only renders. Shared UI helpers in `ui/common.py`.
About 150 lines of business logic sit in `ui/student.py`:
`_handle_new_generation`, `_handle_comparison_generation`,
`_reconcile_generation` and `_pending_age_seconds`
([student.py:336-574](src/genai_cv_game/ui/student.py#L336-L574)). They create
rows, save uploads, start and poll predictions, and apply timeouts. Tests
already import from `ui.student` (`tests/test_student_reconcile.py`) to reach
them.

**Fix:** move them into `src/genai_cv_game/service.py`, or extend
`generation.py`, as plain functions with no `st.*` calls that return results or
errors. The UI then only renders. `student.py` would drop to about 350 lines,
and the UI coverage exclusion becomes honest.

### ✅ Q3. Task validation is written by hand

**Status ✅:** `TaskDefinition` / `VoteImageDefinition` pydantic models with `extra="forbid"` and one model validator for per-mode rules; catalog validated via `TypeAdapter(list[ModelEntry])`.
[tasks.py:15-128](src/genai_cv_game/tasks.py#L15-L128) checks dict fields by
hand, although pydantic is already a dependency. A `TaskDefinition` model with
`Literal` modes and one `@model_validator(mode="after")` for the rules per mode
(edit needs exactly 1 input, vote needs `vote_images`, …) would replace about
100 lines. It would also give better error messages, from
`TypeAdapter(list[TaskDefinition]).validate_json(...)`. The same applies to
`model_catalog.load_models`.

### ✅ Q4. Two status vocabularies, status typed as a string

**Status ✅:** `GenerationStatus` Literal (`pending`/`completed`/`failed`) used by both `GenerationResult` and `Generation`.
`GenerationResult.status` uses `succeeded`
([generation.py](src/genai_cv_game/generation.py)), while the DB and
`Generation` use `completed` ([db.py:12](src/genai_cv_game/db.py#L12)).
`Generation.status` is a `str`. Settle on one vocabulary and type it as a
`Literal`.

### ✅ Q5. Smaller items

**Status ✅ (except UI tests, skipped by decision):** dead code removed (`Vote`, `_row_to_*`, `create_tables`, `_resolve_version`); rows parsed with `model_validate(dict(row))`; generic column migration; `sync_vote_images` in one transaction; `models.json` cached per mtime; path semantics documented in README; `load_dotenv` moved to `app.py`; gallery local import removed; `plural()` helper; `.gitignore` fixed; README drift fixed. mypy clean.
- **Dead code:** `Vote` model and `_row_to_vote`
  ([db.py:625](src/genai_cv_game/db.py#L625)) are unused. `init_db` only wraps
  `create_tables`. `_IMAGE_INPUT_MODES` in `tasks.py` is unused (Q1).
- **Row mappers:** these could be `Model.model_validate(dict(row))` with a
  field validator for JSON and bool columns, which removes about 60 lines in
  [db.py:597-651](src/genai_cv_game/db.py#L597-L651).
- **Repeated disk reads:** `find_model` re-reads and re-validates `models.json`
  for **every gallery card every 5 s**
  ([gallery.py:69](src/genai_cv_game/ui/gallery.py#L69),
  [student.py:596-599](src/genai_cv_game/ui/student.py#L596-L599)). Load once
  with `@st.cache_data`, or hold the catalog in a dict.
- **Half-configurable paths:** `ASSETS_DIR` and `GENERATED_DIR` are settings,
  but the asset paths in `tasks.json` are relative to the working directory and
  the generated image paths are stored in the DB as relative strings. Either
  resolve task paths against `ASSETS_DIR`, or drop the setting.
- **Import side effect:** `load_dotenv()` runs at import time
  ([config.py:9](src/genai_cv_game/config.py#L9)). Move it into `load_settings()`.
- **Odd lookups in the gallery:** a function-local import (`from
  genai_cv_game.db import get_task`) and an extra `get_task` per tick
  ([gallery.py:24-29](src/genai_cv_game/ui/gallery.py#L24-L29)). Pass what's
  needed instead.
- **Duplicated form code:** `_render_prompt_form` and `_render_comparison_form`
  repeat budget arithmetic and pluralisation. Extract `remaining_budget()` and
  a `plural(n, word)` helper.
- **No UI tests:** the UI is untested. A few `streamlit.testing.v1.AppTest`
  smoke tests in stub mode (sign in → generate → share → vote) would catch
  wiring regressions cheaply.
- **Stale `.gitignore`:** it whitelists `data/rounds.json`, which doesn't
  exist, but not `data/tasks.json` (that one only stays tracked because it was
  added earlier). `.claude` is ignored, so new skills or plans won't be
  tracked; `.claude/CLAUDE.md` is tracked only because it was added before.
- **Doc drift:** the README still describes a "password-protected sidebar" and
  a "Choose a task dropdown", but both are now `st.navigation` pages. The env
  table is missing `MODELS_PATH`.

---

## 6. Implementation status (2026-11-07)

Done: S2, S4, S5, C1, C2, U1–U5, D1, D2, D3, D4 (reactions), D6, D8 (hints),
Q1–Q5. Verified with 161 passing tests (93 % coverage), clean mypy, and by
driving the running app in stub mode (sign-in, generation with seed, re-roll,
gallery share/like/favourite/hide, comparison round, vote → reveal → score,
admin stats, projector).

**Before the next class, by hand:**
- Run one real (non-stub) generation per image-capable model on the edit task
  and check the output resembles the source — the C1 field names come from
  Replicate's published schemas.
- Decide on the Gemini watermark (street pair, img_10) (crop, replace, or keep as a teaching point).
- Pick a theme in a browser (`make theme THEME=classroom|studio|lab`).
- Existing `data/app.db` files migrate automatically on start.

**Model catalog change:** `google/imagen-4` was discontinued on Replicate ("Version disabled", 422). Replaced by `ideogram-ai/ideogram-v3-turbo` (different provider, strong text rendering, seed support); Google stays represented by Nano Banana 2. Doc examples now use `google/nano-banana-2`.

**Model catalog update (instructor request):** added `openai/gpt-image-2` (`input_images`, no seed); replaced FLUX 1.1 Pro → `black-forest-labs/flux-3-image` (`images`, no seed), FLUX 2 Flex → `black-forest-labs/flux-2-klein-4b` (`images`, seed), Seedream 4 → `bytedance/seedream-5-pro` (`image_input`, no seed). Field names and seed support taken from Replicate's published schemas; seed now only on Ideogram 3 Turbo and FLUX 2 Klein 4B. C1/D6 notes above describe the catalog at the time of the review.

**New task (instructor request): "I want a refund!"** — explore task: students manipulate a prepared photo (hot dog & fries, bitten burger, restaurant receipt — `assets/input_images/refund/`, supplied by the instructor; origins in `source.txt`), upload their own, or choose *No image — text only* to generate a fake receipt from scratch. Explore tasks can now offer prepared images with friendly labels (`input_image_labels`) and a text-only route (`allow_text_only`, which also unlocks non-image-input models such as Ideogram); the source image is stored per generation and shown as Before | After in the gallery (also for edit tasks). The earlier drawn placeholder images and `scripts/make_refund_inputs.py` were removed. Note: the receipt photo shows a real restaurant (name, address, a first name) and comes from a Facebook post — check that this is fine for a public repository.

**New task (instructor request): "Yummy!"** — text-to-image, two realistic menu photos for a delivery app that must match in style. New task field `gallery_picks` (default 1): students share up to N results, shown side by side in one gallery card; the old one-pick unique index is dropped and the limit enforced in `submit_to_gallery` (oldest pick replaced).

**Zoom for "Real or AI?" (instructor request):** hover zoom + full-screen viewer with pair-linked zoom/pan, built as an inline Custom Component v2 (`ui/zoom.py`, `zoom_image.js`) instead of `streamlit-image-zoom` (legacy v1 iframe component that re-sends the pixels on every rerun). Images are served from `static/` (`enableStaticServing`) and cached by the browser; a 1600 px zoom version loads on first hover. All vote images are now resized to exactly the same pixel size so dimensions cannot leak the label (smaller AI images are upscaled, so they look softer when zoomed — a true resolution difference). Math is tested in QuickJS; the in-browser behaviour has not been seen in a real browser.

**Vote-image quality (instructor request):** audited the processing of the originals. Findings: the real
photos are sRGB JPEGs of 4.6–17 MP; the AI images are PNGs of only 1.1–1.6 MP (long edge 1200–1916 px, one is RGBA
with a fully opaque alpha); no colour-profile problem (reals are sRGB, AI images untagged). What was lossy: JPEG
quality 85/90 with 4:2:0 chroma (colour fringing when zoomed) and a 1600 px zoom size. Now: page 1280 px q92, zoom
2048 px q95, both 4:4:4, identical settings for every image (`scripts/prepare_vote_images.py`).

Why 2048 and not "as large as the originals": all images share the same pixel size (so dimensions can't leak the
label), so enlarging the zoom version upscales the AI images, whose real resolution is limited. Local sharpness at
1:1 (variance of the Laplacian, centre 512 px crop), AI ÷ real, per pair:

| pair | 1280 px | 1600 px | 2048 px | 2400 px |
|---|---|---|---|---|
| portrait | 0.27 | 0.27 | 0.16 | 0.10 |
| plane | 0.64 | 0.84 | 1.22 | 1.03 |
| group | 0.92 | 0.87 | 0.71 | 0.53 |
| houses | 0.85 | 0.44 | 0.25 | 0.19 |
| street | 0.74 | 0.52 | 0.34 | 0.26 |
| window | 0.92 | 0.71 | 0.44 | 0.29 |

At 2400 px (the largest size at which every real photo is still downscaled) the AI image is clearly softer in 5 of 6
pairs — "blurry = AI" becomes a shortcut; at 2048 px the picture is still mixed (in the plane pair the AI image is
the sharper one). The page version stays at 1280 px for the same reason. Change with
`make vote-images` / `scripts/prepare_vote_images.py --zoom-edge N`.

**Blurry thumbnails (instructor report):** the refund picker's thumbnails were `st.image(width=170)`; Streamlit then shrinks the image server-side to exactly 170 px (bilinear), so the browser received 170×255 px (13 KB) — soft on retina screens. Same for the upload preview (320) and the match-target strip (360). Now `ui.common.thumbnail` supplies 3× the pixels (510 px, ~60–95 KB, Lanczos, cached) inside a container of the intended width. The gallery's Before/After and result images were already served at full size (1460 px). The refund receipt is a drawn placeholder until the real photo is dropped in as `quittung.jpg`; the previous photo is kept as git-ignored `quittung_original.jpg`.

**Backlog / ideas:** D4 awards, match scoring, timed rounds · D5 systematic
rating task · D7 reflection notes · text-rendering task from `IDEAS.md` ·
confidence slider in the vote game · UI tests (skipped by decision).
**Won't do / ignored:** S1, S3, S6, C3, D7.
