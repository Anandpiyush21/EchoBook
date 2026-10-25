"""Stage 2b: a fact-checking agent that audits the drafted recipe against the transcript.

The local LLM decides what to look up and what to fix, but every edit goes through a guardrail in
Python: a new quantity must come with a quote that really is in the transcript and contains that
number, and an ingredient can only be removed if the transcript never mentions it. The model can
propose; only the recording can confirm.
"""
import copy
import re
from difflib import SequenceMatcher

from . import agent, config

NUMBER_WORDS = {
    "one": "1", "two": "2", "three": "3", "four": "4", "five": "5", "six": "6",
    "seven": "7", "eight": "8", "nine": "9", "ten": "10", "half": "1/2", "quarter": "1/4",
    "quarters": "3/4", "a": "1", "an": "1",
}
STOPWORDS = {"the", "and", "for", "with", "fresh", "some", "little", "big", "small", "of", "or", "optional"}


def numbers(text: str) -> set[str]:
    words = re.findall(r"[a-z]+|\d+/\d+|\d+", text.lower())
    return {NUMBER_WORDS.get(w, w) for w in words if w in NUMBER_WORDS or w[0].isdigit()}


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9/]+", text.lower())


def _sentences(transcript: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", transcript) if s.strip()]


def _mentions(word: str, transcript_words: set[str]) -> bool:
    # Prefix match tolerates plurals and ASR endings ("chilies" / "chilli", "cloves" / "clove").
    stem = word[:4]
    return any(w.startswith(stem) for w in transcript_words)


def search_transcript(transcript: str, phrase: str, limit: int = 3) -> str:
    """Return the transcript sentences that best match the phrase's keywords."""
    keys = [w for w in _words(phrase) if len(w) >= 3 and w not in STOPWORDS]
    if not keys:
        return "Give at least one keyword to search for."
    scored = []
    for s in _sentences(transcript):
        sw = set(_words(s))
        score = sum(_mentions(k, sw) for k in keys)
        if score:
            scored.append((score, s))
    if not scored:
        return f"The transcript never mentions {phrase!r}."
    scored.sort(key=lambda x: -x[0])
    return "\n".join(f"- \"{s}\"" for _, s in scored[:limit])


def is_in_transcript(quote: str, transcript: str, threshold: float = 0.85) -> bool:
    """True if `quote` (allowing for small ASR / punctuation differences) appears in the transcript."""
    q, t = _words(quote), _words(transcript)
    if not q:
        return False
    if " ".join(q) in " ".join(t):
        return True
    n = len(q)
    target = " ".join(q)
    return any(
        SequenceMatcher(None, " ".join(t[i:i + n]), target).ratio() >= threshold
        for i in range(max(1, len(t) - n + 1))
    )


SYSTEM_PROMPT = """You are a meticulous fact-checker for a family recipe book. A draft recipe was \
written by another model from the speech-to-text transcript of {storyteller}'s voice memo. Small \
models sometimes change amounts ("1 tsp" -> "1/2 tsp") or add ingredients that were never said.

Your job: check EVERY ingredient against the transcript using your tools.
- Use search_transcript to find what was actually said about an ingredient.
- If the spoken amount differs from the draft, call set_quantity with the exact quote as evidence.
- If an ingredient is never mentioned at all, call remove_ingredient.
- Do not change wording style ("2 spoons" is fine), and never guess: if the transcript is unclear, \
leave it alone.
- When you have checked everything, call finish with a one-sentence summary of what you found.
The tools enforce the rules: an edit without real evidence from the transcript is rejected."""


def _ingredient_list(recipe: dict) -> str:
    return "\n".join(
        f"{n}. quantity={i['quantity']!r} item={i['item']!r}" + (f" note={i['note']!r}" if i["note"] else "")
        for n, i in enumerate(recipe["ingredients"], 1)
    )


def check(recipe: dict, transcript: str, on_step=None, max_steps: int = 14) -> tuple[dict, dict]:
    """Audit `recipe` against `transcript`. Returns (possibly corrected recipe, review report)."""
    recipe = copy.deepcopy(recipe)
    ingredients = recipe["ingredients"]
    removed: set[int] = set()
    changes: list[str] = []
    rejected: list[str] = []
    transcript_words = set(_words(transcript))

    def _pick(index) -> dict:
        i = int(index)
        if not 1 <= i <= len(ingredients) or i in removed:
            raise ValueError(f"No ingredient number {index}. Use the numbers from the list.")
        return ingredients[i - 1]

    def set_quantity(index: int, quantity: str, evidence: str) -> str:
        ing = _pick(index)
        if quantity.strip() == ing["quantity"]:
            return "Unchanged: that is already the quantity."
        if not is_in_transcript(evidence, transcript):
            rejected.append(f"set {ing['item']} to {quantity!r}: evidence not found in transcript")
            return "Rejected: that evidence is not in the transcript. Quote the transcript exactly."
        missing = numbers(quantity) - numbers(evidence)
        if missing:
            rejected.append(f"set {ing['item']} to {quantity!r}: evidence doesn't say {', '.join(sorted(missing))}")
            return f"Rejected: the evidence doesn't contain {', '.join(sorted(missing))}."
        changes.append(f"{ing['item']}: {ing['quantity'] or '(none)'} → {quantity.strip()} (“{evidence.strip()}”)")
        ing["quantity"] = quantity.strip()
        return f"Updated ingredient {index}."

    def remove_ingredient(index: int, reason: str = "") -> str:
        ing = _pick(index)
        keys = [w for w in _words(ing["item"]) if len(w) >= 3 and w not in STOPWORDS]
        said = [k for k in keys if _mentions(k, transcript_words)]
        if said:
            rejected.append(f"remove {ing['item']}: transcript mentions {said[0]!r}")
            return f"Rejected: the transcript does mention {said[0]!r}:\n{search_transcript(transcript, said[0], 2)}"
        removed.add(int(index))
        changes.append(f"removed {ing['item']} (never mentioned in the memo)")
        return f"Removed ingredient {index}."

    def finish(summary: str = "") -> str:
        return summary.strip() or "Checked all ingredients."

    tools = [
        agent.Tool("search_transcript", "Find the sentences of the transcript that mention an ingredient or phrase.",
                   agent.params(phrase={"type": "string", "description": "e.g. 'turmeric' or 'cumin seeds'"}),
                   lambda phrase: search_transcript(transcript, phrase)),
        agent.Tool("set_quantity", "Correct an ingredient's quantity to what the speaker actually said.",
                   agent.params(index={"type": "integer", "description": "ingredient number from the list"},
                                quantity={"type": "string", "description": "amount + unit as spoken, e.g. '1 tsp'"},
                                evidence={"type": "string", "description": "the exact transcript words that state it"}),
                   set_quantity),
        agent.Tool("remove_ingredient", "Remove an ingredient the speaker never mentioned.",
                   agent.params(["index"], index={"type": "integer"}, reason={"type": "string"}),
                   remove_ingredient),
        agent.Tool("finish", "Call when every ingredient has been checked.",
                   agent.params(summary={"type": "string", "description": "one sentence about what you found"}),
                   finish),
    ]
    user = (f"Transcript:\n\"\"\"\n{transcript}\n\"\"\"\n\n"
            f"Draft ingredients for {recipe['title']!r}:\n{_ingredient_list(recipe)}")
    result = agent.run(SYSTEM_PROMPT.format(storyteller=config.STORYTELLER), [{"role": "user", "content": user}],
                       tools, max_steps=max_steps, on_step=on_step, stop_tool="finish")

    recipe["ingredients"] = [ing for n, ing in enumerate(ingredients, 1) if n not in removed]
    if not recipe["ingredients"]:  # never let the checker empty a recipe
        recipe["ingredients"] = ingredients
    report = {
        "summary": result.answer,
        "changes": changes,
        "rejected": rejected,
        "lookups": sum(1 for t in result.trace if t["tool"] == "search_transcript"),
        "steps": result.steps,
    }
    return recipe, report
