""""Ask the book": a kitchen-helper agent that answers questions using tools over the recipe book.

The local LLM chooses which tools to call (search, open a recipe, scale it, look up what the
storyteller said in the memo). Arithmetic and lookups happen in Python, so scaled amounts are
exact and quotes are real.
"""
import re
from difflib import SequenceMatcher
from fractions import Fraction

from . import agent, config, db
from .factcheck import search_transcript

SYSTEM_PROMPT = """You are the kitchen helper for "{title}", a family recipe book recovered from \
{storyteller}'s voice memos. Answer the cook's question using your tools:
- search_recipes / list_recipes to find dishes, get_recipe to read one before talking about it.
- scale_recipe whenever the cook wants more or fewer servings. Never do the arithmetic yourself.
- find_in_memo to quote what {storyteller} actually said (tips, stories, why something is done).
Rules: base answers on the book. If the book doesn't have it, say so plainly; you may add general \
cooking advice only if you clearly label it as your own suggestion, not {storyteller}'s. Keep \
answers short and practical, use the recipe's title, and quote {storyteller} when it helps."""

_NUM = r"\d+\s+\d+/\d+|\d+/\d+|\d+(?:\.\d+)?"
_NICE = {Fraction(1, 4): "1/4", Fraction(1, 3): "1/3", Fraction(1, 2): "1/2", Fraction(2, 3): "2/3", Fraction(3, 4): "3/4"}


def _parse(num: str) -> Fraction:
    return sum((Fraction(p) for p in num.split()), Fraction(0))


def _fmt(x: Fraction) -> str:
    whole, frac = divmod(x, 1)
    if frac == 0:
        return str(int(whole))
    nice = min(_NICE, key=lambda f: abs(f - frac))
    if abs(nice - frac) < Fraction(1, 24):
        return f"{int(whole)} {_NICE[nice]}" if whole else _NICE[nice]
    return f"{float(x):.1f}".rstrip("0").rstrip(".")


def scale_quantity(quantity: str, factor: Fraction) -> str:
    """Scale the leading number (or range) in a spoken quantity; leave unmeasured ones as-is."""
    m = re.match(rf"^\s*({_NUM})(?:\s*(?:-|to)\s*({_NUM}))?(.*)$", quantity)
    if not m:
        return f"{quantity} (adjust by eye)" if quantity and quantity != "to taste" else quantity
    lo = _fmt(_parse(m.group(1)) * factor)
    hi = f"-{_fmt(_parse(m.group(2)) * factor)}" if m.group(2) else ""
    return f"{lo}{hi}{m.group(3)}"


def _find(recipe_id: str) -> dict:
    """Look up by id, falling back to the closest title (models often pass the dish name)."""
    entry = db.get(recipe_id)
    if entry:
        return entry
    entries = db.search()
    if not entries:
        raise ValueError("The book is empty.")
    best = max(entries, key=lambda e: SequenceMatcher(None, e["recipe"]["title"].lower(), recipe_id.lower()).ratio())
    if SequenceMatcher(None, best["recipe"]["title"].lower(), recipe_id.lower()).ratio() < 0.4:
        raise ValueError(f"No recipe {recipe_id!r}. Use list_recipes to see what's in the book.")
    return best


def _summary(e: dict) -> dict:
    r = e["recipe"]
    return {"recipe_id": e["id"], "title": r["title"], "description": r["description"], "tags": r["tags"]}


def search_recipes(query: str) -> list[dict] | str:
    hits = db.search(query)
    if not hits:  # all terms must match in db.search; fall back to any term
        seen = {}
        for term in query.split():
            for e in db.search(term):
                seen.setdefault(e["id"], e)
        hits = list(seen.values())
    return [_summary(e) for e in hits] or f"No recipe matches {query!r}. Try list_recipes."


def list_recipes() -> list[dict]:
    return [{"recipe_id": e["id"], "title": e["recipe"]["title"]} for e in db.search()]


def get_recipe(recipe_id: str) -> dict:
    e = _find(recipe_id)
    return {"recipe_id": e["id"], **e["recipe"]}


def scale_recipe(recipe_id: str, factor: float) -> dict:
    if not 0 < float(factor) <= 20:
        raise ValueError("factor must be between 0 and 20 (e.g. 2 to double, 0.5 to halve)")
    e = _find(recipe_id)
    f = Fraction(str(factor)).limit_denominator(12)
    r = e["recipe"]
    return {
        "title": r["title"],
        "original_servings": r["servings"] or "not stated",
        "factor": _fmt(f),
        "ingredients": [
            f"{scale_quantity(i['quantity'], f)} {i['item']}".strip() + (f" ({i['note']})" if i["note"] else "")
            for i in r["ingredients"]
        ],
    }


def find_in_memo(recipe_id: str, phrase: str) -> str:
    e = _find(recipe_id)
    return f"From the memo for {e['recipe']['title']}:\n" + search_transcript(e["transcript"], phrase)


TOOLS = [
    agent.Tool("search_recipes", "Search the book by dish name, ingredient or tag.",
               agent.params(query={"type": "string", "description": "e.g. 'ghee' or 'banana'"}), search_recipes),
    agent.Tool("list_recipes", "List every recipe in the book.", agent.params(), list_recipes),
    agent.Tool("get_recipe", "Read a full recipe: ingredients, steps, tips, servings.",
               agent.params(recipe_id={"type": "string", "description": "recipe_id (or the dish title)"}), get_recipe),
    agent.Tool("scale_recipe", "Scale a recipe's ingredient amounts by a factor (2 = double, 0.5 = half).",
               agent.params(recipe_id={"type": "string"}, factor={"type": "number"}), scale_recipe),
    agent.Tool("find_in_memo", "Find what the storyteller actually said in the voice memo about something.",
               agent.params(recipe_id={"type": "string"}, phrase={"type": "string", "description": "e.g. 'ghee' or 'why'"}),
               find_in_memo),
]


def ask(question: str, history: list[dict] | None = None, on_step=None) -> agent.AgentResult:
    """Answer a cook's question. `history` is prior [{role, content}] turns of this chat."""
    turns = [{"role": t["role"], "content": t["content"]} for t in (history or [])[-6:]
             if t.get("role") in ("user", "assistant") and t.get("content")]
    system = SYSTEM_PROMPT.format(title=config.BOOK_TITLE, storyteller=config.STORYTELLER)
    return agent.run(system, [*turns, {"role": "user", "content": question}], TOOLS,
                     max_steps=8, temperature=0.2, on_step=on_step)
