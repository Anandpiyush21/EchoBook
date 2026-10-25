"""Iterate on the structuring prompt / model without re-running speech-to-text.

    python scripts/eval_structuring.py                 # transcribes sample_audio once, caches, structures
    OLLAMA_MODEL=qwen2.5:7b-instruct python scripts/eval_structuring.py

Prints each recipe plus simple hallucination checks: quantities whose numbers never appear
in the transcript, and story quotes that aren't verbatim.
"""
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import config, structure, transcribe  # noqa: E402

CACHE = config.DATA_DIR / ".transcript_cache.json"
NUMBER_WORDS = {
    "one": "1", "two": "2", "three": "3", "four": "4", "five": "5", "six": "6",
    "seven": "7", "eight": "8", "nine": "9", "ten": "10", "half": "1/2", "quarter": "1/4",
    "quarters": "3/4",
}


def numbers(text: str) -> set[str]:
    words = re.findall(r"[a-z]+|\d+/\d+|\d+", text.lower())
    return {NUMBER_WORDS.get(w, w) for w in words if w in NUMBER_WORDS or w[0].isdigit()}


def main() -> None:
    cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    for audio in sorted(config.SAMPLE_DIR.iterdir()):
        if audio.name not in cache:
            cache[audio.name] = transcribe.transcribe(audio)["text"]
            CACHE.parent.mkdir(parents=True, exist_ok=True)
            CACHE.write_text(json.dumps(cache, indent=1))
        text = cache[audio.name]
        t = time.time()
        recipe = structure.structure(text)
        print(f"===== {audio.name}  ({config.OLLAMA_MODEL}, {time.time() - t:.0f}s)")
        print(json.dumps(recipe, indent=1, ensure_ascii=False))
        spoken = numbers(text)
        for ing in recipe["ingredients"]:
            missing = numbers(ing["quantity"]) - spoken
            if missing:
                print(f"  ! quantity not in transcript: {ing['quantity']!r} {ing['item']}")
        if recipe["story_quote"] not in text:
            print(f"  ! story quote not verbatim: {recipe['story_quote']!r}")


if __name__ == "__main__":
    main()
