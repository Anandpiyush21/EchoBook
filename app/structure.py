"""Stage 2: turn a rambling transcript into a structured recipe with the open-weight LLM (see llm.py)."""
import json
import re
from difflib import SequenceMatcher

from . import config, llm

RECIPE_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "description": {"type": "string"},
        "servings": {"type": "string"},
        "total_time": {"type": "string"},
        "ingredients": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "quantity": {"type": "string"},
                    "item": {"type": "string"},
                    "note": {"type": "string"},
                },
                "required": ["quantity", "item", "note"],
            },
        },
        "steps": {"type": "array", "items": {"type": "string"}},
        "tips": {"type": "array", "items": {"type": "string"}},
        "story_quote": {"type": "string"},
        "tags": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "title", "description", "servings", "total_time",
        "ingredients", "steps", "tips", "story_quote", "tags",
    ],
}

SYSTEM_PROMPT = """You are a careful family-recipe archivist. You receive the raw speech-to-text \
transcript of an elderly relative ("{storyteller}") describing a recipe from memory. Transcripts \
ramble, repeat themselves, contain filler ("okay, is this recording?") and speech-recognition \
mistakes. Turn it into a clean recipe a grandchild could cook from.

Rules:
- Use ONLY what is said in the transcript. Never invent ingredients, quantities, times, \
temperatures or advice. When unsure, leave the field empty rather than guess.
- Copy every amount EXACTLY as spoken: "1 teaspoon" stays "1 tsp", "a pinch" stays "a pinch", \
"a handful" stays "a handful". Never convert or change a number.
- Fix obvious speech-recognition errors in food words (e.g. "pia saffitida" -> "asafoetida", \
"tor dal" -> "toor dal", "asan" -> "Assam").
- ingredients: EVERY ingredient mentioned, in order of use, including ones mentioned casually, \
optional ones ("if you have walnuts", "cinnamon if you like it") and finishing touches (lemon \
juice, fresh herbs).
  "quantity" = amount + unit ONLY, never the ingredient name ("1 cup", "2", "a big pinch", "1 inch \
piece"). Only include a unit the speaker actually said: "four cardamom pods" -> quantity "4", \
item "green cardamom pods". Use "to taste" for unmeasured seasonings, otherwise "".
  "item" = the ingredient name, including words like "fresh" ("fresh coriander"). "note" = preparation or detail as spoken ("chopped fine", \
"very ripe", "optional") or "".
- steps: short imperative steps in the order the speaker does them, one action each, keeping \
the speaker's specific details (times, temperatures, "4 whistles", "repeat 3 times").
- tips: advice or warnings the speaker ACTUALLY says about THIS dish, rephrased briefly. Empty \
list if none.
- servings: as stated ("4 people", "1 loaf", "2 cups"), or "".
- total_time: only if the speaker states a duration for the whole recipe, otherwise "".
- description: one warm sentence describing the dish, without inventing facts.
- story_quote: copy 1-2 consecutive sentences VERBATIM from the transcript about the personal \
memory behind the dish: a person, a place, an occasion, how they learned it. Never cooking \
instructions, never filler like "anyway, that is the dal".
- tags: 2-4 lowercase tags (cuisine, course, key ingredient).
- title: a short, natural dish name in Title Case, using the name the speaker uses for the dish.
Respond with JSON only."""


class StructuringError(RuntimeError):
    pass


def _best_verbatim(quote: str, transcript: str) -> str:
    """Snap the model's quote onto the closest real span of the transcript.

    Small models sometimes paraphrase; the "in their own words" section must be authentic.
    """
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", transcript) if s.strip()]
    if not quote or not sentences:
        return quote
    if quote.strip() in transcript:
        return quote.strip()
    target = quote.lower()
    best, best_score = quote, 0.0
    for size in (1, 2, 3):
        for i in range(len(sentences) - size + 1):
            span = " ".join(sentences[i : i + size])
            score = SequenceMatcher(None, span.lower(), target).ratio()
            if score > best_score:
                best, best_score = span, score
    return best if best_score >= 0.5 else quote


def _clean(data: dict, transcript: str) -> dict:
    def s(v):
        return v.strip() if isinstance(v, str) else ""

    ingredients = []
    for ing in data.get("ingredients") or []:
        if isinstance(ing, dict) and s(ing.get("item")):
            ingredients.append(
                {"quantity": s(ing.get("quantity")), "item": s(ing.get("item")), "note": s(ing.get("note"))}
            )
    steps = [re.sub(r"^\s*\d+[.)]\s*", "", x).strip() for x in data.get("steps") or [] if s(x)]
    recipe = {
        "title": s(data.get("title")) or "Untitled family recipe",
        "description": s(data.get("description")),
        "servings": s(data.get("servings")),
        "total_time": s(data.get("total_time")),
        "ingredients": ingredients,
        "steps": steps,
        "tips": [s(x) for x in data.get("tips") or [] if s(x)],
        "story_quote": _best_verbatim(s(data.get("story_quote")), transcript),
        "tags": sorted({s(x).lower() for x in data.get("tags") or [] if s(x)})[:5],
    }
    if not recipe["ingredients"] or not recipe["steps"]:
        raise StructuringError("Model returned a recipe without ingredients or steps")
    return recipe


def structure(transcript: str, on_token=None, attempts: int = 2) -> dict:
    """Structure a transcript into a recipe dict. `on_token(n)` reports generated token count."""
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT.format(storyteller=config.STORYTELLER)},
        {"role": "user", "content": f"Transcript:\n\"\"\"\n{transcript}\n\"\"\""},
    ]
    last_err = None
    for attempt in range(attempts):
        try:
            raw = llm.generate_json(messages, RECIPE_SCHEMA, 0.1 + 0.2 * attempt, on_token)
            return _clean(json.loads(raw), transcript)
        except llm.LLMError as e:
            raise StructuringError(str(e)) from e
        except (json.JSONDecodeError, StructuringError) as e:
            last_err = e
    raise StructuringError(f"Could not structure recipe: {last_err}")
