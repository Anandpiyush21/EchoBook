"""EchoBook web app: FastAPI backend + static single-page frontend.

Run locally:  uvicorn app.main:app --reload
"""
import re
import shutil
import uuid
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import config, db, export, pipeline

app = FastAPI(title="EchoBook", version="1.0")


@app.on_event("startup")
def _startup() -> None:
    db.init()


def _require_inference() -> None:
    if not config.INFERENCE_ENABLED:
        raise HTTPException(
            403,
            "This is the read-only EchoBook viewer. Recordings are processed on the family's own "
            "machine (ECHOBOOK_MODE=local) so audio never leaves it.",
        )


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40] or "memo"


@app.get("/api/status")
def status() -> dict:
    info = {
        "mode": config.MODE,
        "inference_enabled": config.INFERENCE_ENABLED,
        "storyteller": config.STORYTELLER,
        "book_title": config.BOOK_TITLE,
        "whisper_model": config.WHISPER_MODEL,
        "llm_model": config.OLLAMA_MODEL,
    }
    if config.INFERENCE_ENABLED:
        from .structure import check_ollama

        info["ollama"] = check_ollama()
    return info


@app.get("/api/recipes")
def list_recipes(q: str = "") -> list[dict]:
    return db.search(q)


@app.get("/api/recipes/{recipe_id}")
def get_recipe(recipe_id: str) -> dict:
    entry = db.get(recipe_id)
    if not entry:
        raise HTTPException(404, "Recipe not found")
    return entry


class Ingredient(BaseModel):
    quantity: str = ""
    item: str
    note: str = ""


class RecipeEdit(BaseModel):
    title: str
    description: str = ""
    servings: str = ""
    total_time: str = ""
    ingredients: list[Ingredient]
    steps: list[str]
    tips: list[str] = []
    story_quote: str = ""
    tags: list[str] = []


@app.put("/api/recipes/{recipe_id}")
def update_recipe(recipe_id: str, edit: RecipeEdit) -> dict:
    """Family review: fix anything the model misheard before the recipe is published."""
    _require_inference()
    entry = get_recipe(recipe_id)
    recipe = edit.model_dump()
    recipe["title"] = recipe["title"].strip() or entry["recipe"]["title"]
    recipe["ingredients"] = [i for i in recipe["ingredients"] if i["item"].strip()]
    recipe["steps"] = [s.strip() for s in recipe["steps"] if s.strip()]
    recipe["tips"] = [t.strip() for t in recipe["tips"] if t.strip()]
    recipe["tags"] = sorted({t.strip().lower() for t in recipe["tags"] if t.strip()})
    if not recipe["ingredients"] or not recipe["steps"]:
        raise HTTPException(400, "A recipe needs at least one ingredient and one step")
    entry["recipe"] = recipe
    return db.save(entry)


@app.delete("/api/recipes/{recipe_id}")
def delete_recipe(recipe_id: str) -> dict:
    _require_inference()
    entry = db.delete(recipe_id)
    if not entry:
        raise HTTPException(404, "Recipe not found")
    # Keep the audio if another recipe still points at it.
    if not any(e["audio_file"] == entry["audio_file"] for e in db.search()):
        (config.AUDIO_DIR / entry["audio_file"]).unlink(missing_ok=True)
    return {"deleted": recipe_id}


@app.get("/api/recipes/{recipe_id}/markdown", response_class=PlainTextResponse)
def recipe_markdown(recipe_id: str):
    entry = get_recipe(recipe_id)
    name = _slug(entry["recipe"]["title"])
    return PlainTextResponse(
        export.recipe_markdown(entry),
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{name}.md"'},
    )


@app.get("/api/export/markdown", response_class=PlainTextResponse)
def book_markdown():
    entries = sorted(db.search(), key=lambda e: e["recipe"]["title"])
    return PlainTextResponse(
        export.book_markdown(entries),
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{_slug(config.BOOK_TITLE)}.md"'},
    )


@app.get("/api/samples")
def list_samples() -> list[dict]:
    if not config.INFERENCE_ENABLED or not config.SAMPLE_DIR.exists():
        return []
    return [
        {"name": p.name, "size_kb": p.stat().st_size // 1024}
        for p in sorted(config.SAMPLE_DIR.iterdir())
        if p.suffix.lower() in config.ALLOWED_AUDIO
    ]


@app.get("/samples/{name}")
def sample_audio(name: str):
    path = config.SAMPLE_DIR / Path(name).name
    if not config.INFERENCE_ENABLED or not path.is_file():
        raise HTTPException(404)
    return FileResponse(path)


class SampleRequest(BaseModel):
    name: str


@app.post("/api/process/sample")
def process_sample(req: SampleRequest) -> dict:
    _require_inference()
    src = config.SAMPLE_DIR / Path(req.name).name
    if not src.is_file():
        raise HTTPException(404, "Sample not found")
    dest = f"{_slug(src.stem)}-{uuid.uuid4().hex[:6]}{src.suffix.lower()}"
    shutil.copy(src, config.AUDIO_DIR / dest)
    return pipeline.submit(dest, src.name)


@app.post("/api/process/upload")
def process_upload(file: UploadFile = File(...)) -> dict:
    _require_inference()
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in config.ALLOWED_AUDIO:
        raise HTTPException(400, f"Unsupported file type {suffix!r}. Try: {', '.join(sorted(config.ALLOWED_AUDIO))}")
    dest = f"{_slug(Path(file.filename).stem)}-{uuid.uuid4().hex[:6]}{suffix}"
    path = config.AUDIO_DIR / dest
    limit, written = config.MAX_UPLOAD_MB * 1024 * 1024, 0
    with path.open("wb") as out:
        while chunk := file.file.read(1024 * 1024):
            written += len(chunk)
            if written > limit:
                out.close()
                path.unlink(missing_ok=True)
                raise HTTPException(413, f"File is larger than {config.MAX_UPLOAD_MB} MB")
            out.write(chunk)
    return pipeline.submit(dest, file.filename)


@app.get("/api/jobs/{job_id}")
def job_status(job_id: str) -> dict:
    job = pipeline.get(job_id)
    if not job:
        raise HTTPException(404, "Unknown job (the server may have restarted)")
    return job


@app.get("/healthz")
def healthz() -> dict:
    return {"ok": True}


config.AUDIO_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/audio", StaticFiles(directory=config.AUDIO_DIR), name="audio")
app.mount("/", StaticFiles(directory=config.FRONTEND_DIR, html=True), name="frontend")
