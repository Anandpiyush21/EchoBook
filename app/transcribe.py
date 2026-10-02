"""Stage 1: local speech-to-text with faster-whisper (open-weight Whisper on CTranslate2)."""
import threading
from pathlib import Path

from . import config

# Biasing Whisper toward kitchen vocabulary noticeably improves words like "asafoetida" or "ghee".
INITIAL_PROMPT = (
    "A grandparent's voice memo describing a family recipe from memory: ingredients, "
    "cups, teaspoons, tablespoons, grams, ghee, cumin, turmeric, cardamom, asafoetida, "
    "toor dal, masala, flour, butter, Fahrenheit, Celsius."
)

_model = None
_lock = threading.Lock()


def _load():
    global _model
    with _lock:
        if _model is None:
            from faster_whisper import WhisperModel

            _model = WhisperModel(
                config.WHISPER_MODEL,
                device=config.WHISPER_DEVICE,
                compute_type=config.WHISPER_COMPUTE_TYPE,
            )
    return _model


def transcribe(path: Path, on_progress=None) -> dict:
    """Transcribe an audio file. `on_progress(fraction)` is called as segments arrive."""
    model = _load()
    segments, info = model.transcribe(
        str(path),
        beam_size=5,
        vad_filter=True,
        initial_prompt=INITIAL_PROMPT,
    )
    parts = []
    for seg in segments:  # generator: decoding happens lazily as we iterate
        parts.append(seg.text.strip())
        if on_progress and info.duration:
            on_progress(min(seg.end / info.duration, 1.0))
    return {
        "text": " ".join(p for p in parts if p),
        "language": info.language,
        "duration": round(info.duration, 1),
    }
