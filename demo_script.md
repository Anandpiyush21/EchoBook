# EchoBook demo script

A 2–3 minute demo video in two parts: the **local pipeline** (where the open-weight models run) and the
**live Render link** (what family members see).

## Before you hit record

```bash
cd EchoBook && source .venv/bin/activate
ollama serve                                # if it isn't already running as a service
ollama run qwen2.5:7b-instruct "hi" >/dev/null   # warm the model so the demo doesn't wait for loading
uvicorn app.main:app --port 8000
```

- Open http://localhost:8000. The book should already show the three sample recipes (from `data/recipes.json`).
- To process a memo live, delete one recipe first (open it → **Delete**), e.g. *Masala Chai*, the
  shortest memo (48 s), so the live run is the quickest.
- Optional, for the "offline" moment: turn off Wi-Fi / unplug ethernet, and run uvicorn with `HF_HUB_OFFLINE=1`.
- Timing: on a GPU the whole run takes seconds. On CPU expect about 2 minutes for the 48 s chai memo (with `OLLAMA_NUM_GPU=0`),
  so either cut the wait in editing or use `OLLAMA_MODEL=qwen2.5:3b-instruct` for the recording.

## Scene 1: the problem (15 s)

Narration: *"My grandfather has years of voice memos describing family recipes. No ingredient lists, no
steps, just him talking. Here's one."*

- Go to **Add a memo**. Under "or try one of the sample memos", press ▶ on **masala chai** and let it play
  5–10 seconds ("Ah, the chai. People think chai is just tea bags, no no no…").

## Scene 2: the local pipeline (60–90 s)

1. *(Optional)* show the network is off.
2. Click **Turn into recipe** next to *masala chai*.
3. Point out the stages as they light up:
   - **Saving the recording**: "stored on this computer only".
   - **Listening**: the progress bar fills as faster-whisper transcribes locally, and the raw transcript
     appears in italics, filler and mistakes included.
   - **Writing the recipe**: "N tokens written" counts up while qwen2.5 running in Ollama structures it
     into JSON.
   - **Adding to the book** → ✓.
4. The finished recipe card renders below. Click **Open the recipe →**.

**Expected output for masala chai** (wording varies slightly run to run):
- Title *Masala Chai* (or *Chai*), serves **2 cups**.
- Ingredients: 1 cup water, 1 cup milk, 4 green cardamom pods, 1 inch ginger, 2 cloves, cinnamon (optional),
  2 tsp loose black tea (Assam), 2 tsp sugar.
- Steps ending with "boil until it rises, take it off the flame, let it settle, repeat 3 times" → strain.
- **In Grandpa's words**: *"I drank this every morning at the railway station for 40 years before work…
  he taught me the three times trick."*, with the audio player under it.

## Scene 3: the book (30 s)

1. Click **Recipes**. Three cards.
2. Type **ghee** in search → only the Sunday dal remains, with "ghee" highlighted as a matched ingredient.
   Try **cardamom** → chai. Clear the search.
3. Open **Sunday Dal** → scroll: quantities exactly as spoken ("a big pinch" of asafoetida, "4 whistles"),
   Grandpa's tips, the quote about the day "your father was born". Press ▶ on the audio player.
4. Expand **Original voice memo transcript** to show the raw ramble next to the clean card.
5. Click **Print book** → cover, contents, one recipe per page → **Print / Save as PDF**. Show the PDF preview.

## Scene 4: the shareable link (20 s)

1. Open the Render URL (e.g. `https://echobook.onrender.com`). Same book, with a green banner: *"Read-only
   family copy… audio and processing never touched the cloud."*
2. Click **Add a memo** → it explains processing happens at home. That's the design: the cloud only ever
   sees finished recipes the family chose to publish.
3. Narration: *"New recipes are processed on Grandpa's computer, then a git push publishes them here."*

## Closing line

*"Whisper and Qwen are open-weight, so Grandpa's voice never leaves home, there's no per-recording API bill,
and it'll still work in twenty years when the APIs are gone."*

## Troubleshooting

| Symptom | Fix |
|---|---|
| ⚠ "Ollama isn't running" on Add page | `ollama serve` |
| ⚠ "Model … isn't pulled yet" | `ollama pull qwen2.5:7b-instruct` |
| "Listening" stays at 0% for a while on first run | Whisper model downloading (~500 MB, once) |
| Writing the recipe takes minutes | CPU-only; use `OLLAMA_MODEL=qwen2.5:3b-instruct` or a GPU |
| Render link slow to open | Free tier is waking up (~30 s) |
