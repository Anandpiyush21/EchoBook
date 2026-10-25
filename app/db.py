"""Stage 3: SQLite storage, mirrored to a JSON snapshot (data/recipes.json).

The snapshot is what gets committed and deployed: the read-only viewer on Render rebuilds its
SQLite database from it at startup, so inference never has to run in the cloud.
"""
import json
import sqlite3
import threading
from datetime import datetime, timezone

from . import config

_lock = threading.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS recipes (
    id          TEXT PRIMARY KEY,
    title       TEXT NOT NULL,
    recipe_json TEXT NOT NULL,
    transcript  TEXT NOT NULL,
    audio_file  TEXT NOT NULL,
    source_name TEXT NOT NULL,
    duration    REAL,
    asr_model   TEXT,
    llm_model   TEXT,
    created_at  TEXT NOT NULL,
    search_text TEXT NOT NULL
);
"""


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(config.DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _search_text(recipe: dict) -> str:
    parts = [recipe["title"], recipe.get("description", ""), " ".join(recipe.get("tags", []))]
    parts += [i["item"] for i in recipe.get("ingredients", [])]
    return " ".join(parts).lower()


def _row_to_dict(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "recipe": json.loads(row["recipe_json"]),
        "transcript": row["transcript"],
        "audio_file": row["audio_file"],
        "source_name": row["source_name"],
        "duration": row["duration"],
        "asr_model": row["asr_model"],
        "llm_model": row["llm_model"],
        "created_at": row["created_at"],
    }


def _insert(conn: sqlite3.Connection, entry: dict) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO recipes VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (
            entry["id"], entry["recipe"]["title"], json.dumps(entry["recipe"], ensure_ascii=False),
            entry["transcript"], entry["audio_file"], entry["source_name"], entry.get("duration"),
            entry.get("asr_model"), entry.get("llm_model"), entry["created_at"],
            _search_text(entry["recipe"]),
        ),
    )


def init() -> None:
    config.AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    with _lock, _connect() as conn:
        conn.executescript(SCHEMA)
        empty = conn.execute("SELECT COUNT(*) FROM recipes").fetchone()[0] == 0
        if empty and config.SEED_PATH.exists():
            for entry in json.loads(config.SEED_PATH.read_text()):
                _insert(conn, entry)


def _write_snapshot(conn: sqlite3.Connection) -> None:
    rows = conn.execute("SELECT * FROM recipes ORDER BY created_at").fetchall()
    tmp = config.SEED_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps([_row_to_dict(r) for r in rows], indent=1, ensure_ascii=False))
    tmp.replace(config.SEED_PATH)


def save(entry: dict) -> dict:
    entry.setdefault("created_at", datetime.now(timezone.utc).isoformat(timespec="seconds"))
    with _lock, _connect() as conn:
        _insert(conn, entry)
        _write_snapshot(conn)
    return entry


def delete(recipe_id: str) -> dict | None:
    with _lock, _connect() as conn:
        row = conn.execute("SELECT * FROM recipes WHERE id = ?", (recipe_id,)).fetchone()
        if row:
            conn.execute("DELETE FROM recipes WHERE id = ?", (recipe_id,))
            _write_snapshot(conn)
    return _row_to_dict(row) if row else None


def get(recipe_id: str) -> dict | None:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM recipes WHERE id = ?", (recipe_id,)).fetchone()
    return _row_to_dict(row) if row else None


def search(query: str = "") -> list[dict]:
    """Every whitespace-separated term must match the title, tags or an ingredient."""
    sql, params = "SELECT * FROM recipes", []
    terms = [t for t in query.lower().split() if t]
    if terms:
        sql += " WHERE " + " AND ".join("search_text LIKE ?" for _ in terms)
        params = [f"%{t}%" for t in terms]
    with _connect() as conn:
        rows = conn.execute(sql + " ORDER BY created_at DESC", params).fetchall()
    return [_row_to_dict(r) for r in rows]
