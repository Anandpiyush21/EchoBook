# EchoBook

**Turn family voice memos into a living recipe book, entirely on your own computer.**

*Made for Hacktoberfest, Kramer Community.*

My grandfather has years of voice memos describing family recipes from memory. They ramble, there are no
ingredient lists and no steps, and the recipes only exist in his voice, scattered across audio files.
EchoBook takes those recordings and turns them into a clean, searchable, printable recipe book. It keeps
the important part: his own words and the original recording, attached to every recipe.

Everything runs on open-weight models, and you choose where the LLM runs with one setting:

- **Ollama (default, fully offline):** `qwen2.5` runs on your own machine. No recording, transcript or
  family story leaves the house, and once the models are downloaded the pipeline works with no internet.
- **Gemma 4 via the Gemini API:** Google's open-weight `gemma-4-26b-a4b-it` does the writing and powers
  both agents, with no GPU needed. Speech-to-text still runs locally, so only the transcript is sent.

![EchoBook demo](docs/demo.gif)

![The recipe book](docs/book.png)

| A recipe, with Grandpa's own words and the original recording | Add a memo: upload, record or try a sample |
|---|---|
| ![Recipe page](docs/recipe.png) | ![Add a memo](docs/add.png) |

## Features

- **Drop in a voice memo** (mp3, m4a, wav, ogg, webm…), **record one with your mic** right in the browser,
  or pick a sample, and watch each stage run live: saving → listening (speech-to-text, with a progress bar
  and live transcript) → writing the recipe → fact-checking → adding it to the book.
- **Two model backends**: local Ollama (`qwen2.5`) or Gemma 4 through the Gemini API, switched with
  `LLM_PROVIDER`. The footer always shows which models produced the book.
- **Fact-checker agent**: after the recipe is written, an agent checks every ingredient against the
  transcript and fixes amounts the recording supports. Guardrails in code block anything it doesn't.
- **"Ask the book"**: chat with the recipes ("make masala chai for 6 people", "why real ghee?"). A
  tool-calling agent searches, scales and quotes the memos.
- **Recipe cards**: title, servings, ingredient list with quantities exactly as spoken, numbered steps,
  and the storyteller's own tips.
- **"In Grandpa's words"**: a verbatim quote of the personal story behind each dish (who taught it, when it
  was made), shown next to an audio player with the original recording.
- **Review & edit**: small models occasionally mishear, so every recipe can be checked against the
  recording and corrected before the book is shared.
- **Search** by dish or ingredient ("ghee", "cardamom"), with matching ingredients highlighted.
- **Export**: download any recipe or the whole book as Markdown, or open the print layout (cover, table
  of contents, one recipe per page) and save it as a PDF.
- **Shareable read-only copy** deployed on Render: relatives can browse the book and listen to the
  recordings, while all processing stays at home.

## How it works

```
                  ┌──────────────────────── family computer (offline-capable) ───────────────────────┐
 voice memo  ──►  │ 1. faster-whisper        2. Ollama + qwen2.5:7b        3. SQLite                 │
 (.m4a/.wav)      │    open-weight Whisper ─►   JSON-schema-constrained ─►   recipes + transcript   │
                  │    small.en, on-device      recipe extraction              + link to audio      │
                  │                                                              │                  │
                  │    FastAPI + single-page UI  (ECHOBOOK_MODE=local)            ▼                  │
                  │                                                    data/recipes.json + data/audio│
                  └──────────────────────────────────────────────────────────────┬──────────────────┘
                                                                   git push      │  (finished recipes only)
                                                                                 ▼
                                                   Render: same FastAPI app, ECHOBOOK_MODE=viewer
                                                   read-only browse / search / listen / print
```

1. **Speech-to-text: [faster-whisper](https://github.com/SYSTRAN/faster-whisper)** runs OpenAI's
   open-weight Whisper (`small.en` by default) on CTranslate2 with int8 on CPU or float16 on a GPU. VAD
   filtering skips silence, and an initial prompt biases it toward kitchen vocabulary (ghee, asafoetida,
   cardamom…). See `app/transcribe.py`.
2. **Structuring: [Ollama](https://ollama.com) + `qwen2.5:7b-instruct`** (Apache-2.0, open weights), or
   **Gemma 4** (`gemma-4-26b-a4b-it`) through the Gemini API with `LLM_PROVIDER=gemma`. The
   transcript is sent to the local model with a carefully tuned archivist prompt, and Ollama's
   **structured outputs** constrain decoding to a JSON schema (title, servings, ingredients with
   quantity/item/note, steps, tips, story quote, tags), so the output always parses. The prompt forbids
   invented quantities, times and advice, and makes the model copy amounts exactly as spoken. After
   generation, the story quote is snapped back onto the closest real span of the transcript so the "in
   their own words" section is always authentic. See `app/structure.py`.
3. **Storage: SQLite** (`data/echobook.db`) holds each recipe, its full transcript, the source audio file
   and which models produced it. Every change is mirrored to `data/recipes.json`, a diffable snapshot that
   gets committed and deployed.
4. **Web app: FastAPI + plain HTML/CSS/JS** with no build step and no framework. Long pipeline runs happen
   in a background worker, and the UI polls `/api/jobs/{id}` for stage, progress and token counts.

### Agents on the open-weight model

On top of the pipeline, two **tool-calling agents** run on the same open-weight model, using its native
function calling (`app/agent.py`, a ~100-line agent loop with no framework). The model chooses which
tool to call next. Python runs the tool and returns the result, until the model answers.

The model backend is one setting (`app/llm.py`):

| `LLM_PROVIDER` | Model | Notes |
|---|---|---|
| `ollama` (default) | `qwen2.5` on your own machine | fully offline, private |
| `gemma` | Google's open-weight **Gemma 4** (`gemma-4-26b-a4b-it`) via the Gemini API | needs a free `GEMINI_API_KEY`; no GPU, so "Ask the book" can also run on the hosted Render viewer |

- **Fact-checker agent** (`app/factcheck.py`) is a pipeline stage after structuring. It checks every
  ingredient against the transcript with `search_transcript`, and can call `set_quantity` or
  `remove_ingredient`. **Guardrails in code** reject any edit the recording doesn't support: a new amount
  needs a quote that really is in the transcript and contains that number, and an ingredient can only be
  removed if it is never mentioned. Every tool call streams live into the progress view, and the recipe
  page shows what the agent changed and which edits the guardrails blocked.
- **"Ask the book" kitchen agent** (`app/kitchen.py`, `POST /api/ask`) is a chat page with the tools
  `search_recipes`, `list_recipes`, `get_recipe`, `scale_recipe` and `find_in_memo`. Ask "double the banana
  bread" and it finds the recipe and scales it. The arithmetic is exact because Python does it, not the
  model. Ask "why real ghee?" and it quotes Grandpa's memo. Each tool call is shown as the agent makes it.

### Why the local / cloud split?

GPU inference doesn't fit on Render's free tier, and it shouldn't run in the cloud anyway, because the
point is that family recordings stay home. So the same codebase runs in two modes:

| | `ECHOBOOK_MODE=local` (home) | `ECHOBOOK_MODE=viewer` (Render) |
|---|---|---|
| Upload & process memos | ✅ faster-whisper + Ollama | ❌ disabled (403) |
| Browse, search, listen, export | ✅ | ✅ |
| Ask the book (agent) | ✅ | ✅ when `LLM_PROVIDER=gemma` and `GEMINI_API_KEY` are set |
| Dependencies | `requirements.txt` (includes faster-whisper) | `requirements-web.txt` (FastAPI only) |
| Data | SQLite, mirrored to `data/recipes.json` | SQLite rebuilt from `data/recipes.json` at boot |

Publishing new recipes: process memos at home, review them, then `git commit data/ && git push`. Render
auto-deploys the updated book.

## Run it locally

Requirements: Python 3.10+, [Ollama](https://ollama.com/download). A GPU is optional: on a 12-core CPU a
one-minute memo takes about 2 minutes end to end with the 7B model (~15 s to transcribe, the rest to
structure), or about half that with `qwen2.5:3b-instruct`. On a GPU the whole pipeline takes seconds.
If your machine has only a small GPU, set `OLLAMA_NUM_GPU=0`. A partial offload onto a weak GPU was 6x
slower at prompt processing than pure CPU in my tests.

```bash
git clone https://github.com/Anandpiyush21/EchoBook.git && cd EchoBook
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

ollama pull qwen2.5:7b-instruct      # one-time download (~4.7 GB); or qwen2.5:3b-instruct for speed
cp .env.example .env                 # optional: change models, storyteller name, book title

uvicorn app.main:app --port 8000
# open http://localhost:8000  →  "Add a memo"  →  pick a sample  →  "Turn into recipe"
```

**Using Gemma 4 instead of Ollama:** skip `ollama pull`, get a free key at
https://aistudio.google.com/apikey, and set `LLM_PROVIDER=gemma` and `GEMINI_API_KEY=...` in `.env`.
Structuring and both agents then run on `gemma-4-26b-a4b-it` (or `gemma-4-31b-it` via `GEMMA_MODEL`).

The first transcription downloads the Whisper model (~500 MB) from Hugging Face. No token is needed.
After that, set `HF_HUB_OFFLINE=1`, unplug the network, and the whole pipeline still works.

**Using a GPU** (e.g. an RTX A6000): Ollama uses CUDA automatically. For Whisper, install the CUDA
libraries faster-whisper needs (`pip install nvidia-cublas-cu12 nvidia-cudnn-cu12`) and set
`WHISPER_MODEL=large-v3` and `OLLAMA_MODEL=qwen2.5:14b-instruct` for the best quality.

## Deploy the viewer on Render

1. Push this repo to GitHub (the processed recipes in `data/` included).
2. In Render: **New → Blueprint**, select the repo. `render.yaml` creates a free Python web service with
   `ECHOBOOK_MODE=viewer`.
3. Every push to `main` redeploys. New recipes processed at home show up after `git push`.

The viewer installs only FastAPI and uvicorn, so builds take seconds and fit the free tier. (Free
instances sleep when idle, so the first visit can take ~30 s to wake.)

## Project layout

```
app/
  main.py          FastAPI routes (recipes, search, export, upload/sample processing, job status)
  transcribe.py    stage 1: faster-whisper speech-to-text
  structure.py     stage 2: Ollama prompt + JSON schema + output cleaning / verbatim-quote check
  pipeline.py      background worker, per-stage job progress
  db.py            stage 3: SQLite store, mirrored to data/recipes.json
  export.py        Markdown export
  llm.py           model backend switch (Ollama or Gemma via the Gemini API)
  agent.py         minimal tool-calling agent loop
  factcheck.py     fact-checker agent: verifies ingredients against the transcript
  kitchen.py       "Ask the book" agent: search, scale and quote recipes
  config.py        env-driven settings (.env supported)
frontend/          index.html, app.js, style.css (single-page app, no build step)
sample_audio/      three stand-in voice memos (see below)
data/              recipes.json snapshot + audio for the deployed book
scripts/
  eval_structuring.py   iterate on the prompt/model without re-transcribing; flags hallucinated quantities
  make_sample_audio.py  regenerate the stand-in memos with Piper TTS
render.yaml        Render Blueprint (viewer mode)
demo_script.md     step-by-step live demo
```

## About the sample memos

`sample_audio/` holds three rambling, unscripted-sounding memos (Sunday dal, banana bread, masala chai),
written in the style of my grandfather's recordings and voiced with [Piper](https://github.com/rhasspy/piper),
an open-source local TTS (`scripts/make_sample_audio.py`), so the demo works without sharing private family
audio. They include the things real memos have: false starts, asides, a bit of family history and loose
measurements ("a big pinch of hing"). Drop in real recordings and they work the same way.

## Prompt-tuning notes

`scripts/eval_structuring.py` re-runs only the structuring step over cached transcripts and flags any
ingredient quantity whose numbers never appear in the transcript. Findings that shaped the prompt:

- `qwen2.5:3b` was fast but invented details (a "30 minutes" total time, a "don't over-mix" tip on a dal)
  and changed amounts (1 tsp → ½ tsp). `qwen2.5:7b` with the tightened prompt copied amounts exactly and
  left unknown fields empty.
- Giving the model an example ASR correction involving "Assam" made it name unrelated dishes "Assam …".
  The examples in a prompt leak, so they have to be chosen carefully.
- Small models paraphrase "verbatim" quotes, hence the fuzzy snap-back onto the real transcript.

## License

MIT
