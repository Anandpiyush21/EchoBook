"""Background job runner: audio -> transcript -> recipe -> storage, with per-stage progress."""
import queue
import threading
import time
import traceback
import uuid
from pathlib import Path

from . import config, db

_jobs: dict[str, dict] = {}
_queue: "queue.Queue[str]" = queue.Queue()
_worker_started = False
_start_lock = threading.Lock()


def _update(job_id: str, **fields) -> None:
    _jobs[job_id].update(fields, updated_at=time.time())


def _run(job_id: str) -> None:
    # Imported lazily so the viewer deployment never needs faster-whisper installed.
    from . import structure, transcribe

    job = _jobs[job_id]
    audio = config.AUDIO_DIR / job["audio_file"]

    _update(job_id, stage="transcribing", progress=0.0, started_at=time.time())
    result = transcribe.transcribe(audio, on_progress=lambda p: _update(job_id, progress=p))
    if not result["text"].strip():
        raise RuntimeError("No speech was detected in this recording.")
    _update(job_id, stage="structuring", progress=None, transcript=result["text"], tokens=0)

    recipe = structure.structure(result["text"], on_token=lambda n: _update(job_id, tokens=n))
    _update(job_id, stage="saving")

    entry = db.save({
        "id": job["recipe_id"],
        "recipe": recipe,
        "transcript": result["text"],
        "audio_file": job["audio_file"],
        "source_name": job["source_name"],
        "duration": result["duration"],
        "asr_model": f"faster-whisper {config.WHISPER_MODEL}",
        "llm_model": f"ollama {config.OLLAMA_MODEL}",
    })
    _update(job_id, stage="done", recipe_id=entry["id"], finished_at=time.time())


def _worker() -> None:
    # One job at a time: the models are big, and serial processing keeps memory predictable.
    while True:
        job_id = _queue.get()
        try:
            _run(job_id)
        except Exception as e:  # surface any failure to the UI instead of dying silently
            traceback.print_exc()
            _update(job_id, stage="error", error=str(e))


def submit(audio_file: str, source_name: str) -> dict:
    global _worker_started
    with _start_lock:
        if not _worker_started:
            threading.Thread(target=_worker, daemon=True).start()
            _worker_started = True
    job_id = uuid.uuid4().hex[:12]
    _jobs[job_id] = {
        "id": job_id,
        "recipe_id": Path(audio_file).stem,
        "audio_file": audio_file,
        "source_name": source_name,
        "stage": "queued",
        "progress": None,
        "created_at": time.time(),
        "updated_at": time.time(),
    }
    _queue.put(job_id)
    return _jobs[job_id]


def get(job_id: str) -> dict | None:
    return _jobs.get(job_id)
