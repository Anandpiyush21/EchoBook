"""Markdown export for a single recipe or the whole book."""
from . import config


def recipe_markdown(entry: dict, level: int = 1) -> str:
    r = entry["recipe"]
    h = "#" * level
    lines = [f"{h} {r['title']}", ""]
    if r.get("description"):
        lines += [f"*{r['description']}*", ""]
    meta = [m for m in (
        f"**Serves:** {r['servings']}" if r.get("servings") else "",
        f"**Time:** {r['total_time']}" if r.get("total_time") else "",
    ) if m]
    if meta:
        lines += [" · ".join(meta), ""]
    if r.get("story_quote"):
        lines += [f"> “{r['story_quote']}”", f"> — {config.STORYTELLER}", ""]
    lines += [f"{h}# Ingredients", ""]
    for i in r["ingredients"]:
        qty = f"{i['quantity']} " if i.get("quantity") else ""
        note = f", {i['note']}" if i.get("note") else ""
        lines.append(f"- {qty}{i['item']}{note}")
    lines += ["", f"{h}# Steps", ""]
    lines += [f"{n}. {s}" for n, s in enumerate(r["steps"], 1)]
    if r.get("tips"):
        lines += ["", f"{h}# {config.STORYTELLER}'s tips", ""]
        lines += [f"- {t}" for t in r["tips"]]
    lines += ["", f"<details><summary>Original voice memo transcript</summary>", "",
              entry["transcript"], "", "</details>", ""]
    return "\n".join(lines)


def book_markdown(entries: list[dict]) -> str:
    out = [f"# {config.BOOK_TITLE}", "",
           f"*{len(entries)} family recipes, transcribed from voice memos with EchoBook.*", "",
           "## Contents", ""]
    out += [f"{n}. {e['recipe']['title']}" for n, e in enumerate(entries, 1)]
    out.append("")
    for e in entries:
        out += ["---", "", recipe_markdown(e, level=2)]
    return "\n".join(out)
