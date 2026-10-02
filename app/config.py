"""Runtime settings, read from environment variables (see .env.example)."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv() -> None:
    env = ROOT / ".env"
    if not env.exists():
        return
    for line in env.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            value = value.split(" #", 1)[0].strip().strip('"').strip("'")
            os.environ.setdefault(key.strip(), value)


_load_dotenv()

# "local"  -> full pipeline: upload, transcribe (faster-whisper), structure (Ollama).
# "viewer" -> read-only recipe book; used for the public Render deployment.
MODE = os.getenv("ECHOBOOK_MODE", "local").lower()
INFERENCE_ENABLED = MODE == "local"

DATA_DIR = Path(os.getenv("ECHOBOOK_DATA_DIR", ROOT / "data"))
AUDIO_DIR = DATA_DIR / "audio"
DB_PATH = DATA_DIR / "echobook.db"
SEED_PATH = DATA_DIR / "recipes.json"  # committed snapshot that the viewer deployment loads
SAMPLE_DIR = ROOT / "sample_audio"
FRONTEND_DIR = ROOT / "frontend"

WHISPER_MODEL = os.getenv("WHISPER_MODEL", "small.en")
WHISPER_DEVICE = os.getenv("WHISPER_DEVICE", "auto")  # auto | cpu | cuda
WHISPER_COMPUTE_TYPE = os.getenv("WHISPER_COMPUTE_TYPE", "auto")  # e.g. int8 on CPU, float16 on GPU

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:7b-instruct")
# Layers to offload to the GPU; leave unset to let Ollama decide. Set 0 to force CPU, which is faster
# than a partial offload onto a small GPU.
OLLAMA_NUM_GPU = os.getenv("OLLAMA_NUM_GPU")

STORYTELLER = os.getenv("ECHOBOOK_STORYTELLER", "Grandpa")
BOOK_TITLE = os.getenv("ECHOBOOK_TITLE", "Grandpa's Kitchen")

ALLOWED_AUDIO = {".wav", ".mp3", ".m4a", ".ogg", ".opus", ".webm", ".flac", ".aac", ".mp4"}
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "100"))
