"""LLM backends for the open-weight models: local Ollama, or Gemma through the Gemini API.

Both return messages in Ollama's shape ({"content", "tool_calls"}) so the agent loop and the
structuring step don't care which one is running. Pick with LLM_PROVIDER=ollama | gemma.
"""
import json
import re

import httpx

from . import config

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


class LLMError(RuntimeError):
    pass


def model_label() -> str:
    return f"gemma {config.GEMMA_MODEL} (Gemini API)" if config.LLM_PROVIDER == "gemma" else f"ollama {config.OLLAMA_MODEL}"


def check() -> dict:
    """Whether the configured backend is reachable and ready."""
    if config.LLM_PROVIDER == "gemma":
        return {"ok": bool(config.GEMINI_API_KEY), "running": bool(config.GEMINI_API_KEY),
                "provider": "gemma", "model": config.GEMMA_MODEL}
    try:
        r = httpx.get(f"{config.OLLAMA_URL}/api/tags", timeout=3)
        r.raise_for_status()
        names = {m["name"] for m in r.json().get("models", [])}
        wanted = config.OLLAMA_MODEL if ":" in config.OLLAMA_MODEL else f"{config.OLLAMA_MODEL}:latest"
        return {"ok": wanted in names, "running": True, "provider": "ollama", "model": config.OLLAMA_MODEL}
    except Exception:
        return {"ok": False, "running": False, "provider": "ollama", "model": config.OLLAMA_MODEL}


# ---------- Ollama ----------

def _ollama_options(temperature: float) -> dict:
    options = {"temperature": temperature, "num_ctx": 8192}
    if config.OLLAMA_NUM_GPU not in (None, ""):
        options["num_gpu"] = int(config.OLLAMA_NUM_GPU)
    return options


def _ollama_chat(messages: list, tools: list[dict], temperature: float) -> dict:
    payload = {"model": config.OLLAMA_MODEL, "messages": messages, "tools": tools, "stream": False,
               "options": _ollama_options(temperature), "keep_alive": "30m"}
    try:
        r = httpx.post(f"{config.OLLAMA_URL}/api/chat", json=payload, timeout=900)
    except httpx.ConnectError as e:
        raise LLMError(f"Can't reach Ollama at {config.OLLAMA_URL}. Is `ollama serve` running?") from e
    if r.status_code != 200:
        raise LLMError(f"Ollama returned {r.status_code}: {r.text[:200]}")
    return r.json().get("message", {})


def _ollama_json(messages: list, schema: dict, temperature: float, on_token=None) -> str:
    payload = {
        "model": config.OLLAMA_MODEL,
        "messages": messages,
        "format": schema,  # Ollama structured outputs: decoding is constrained to the schema
        "stream": True,
        "options": _ollama_options(temperature),
        "keep_alive": "30m",
    }
    chunks = []
    try:
        with httpx.stream("POST", f"{config.OLLAMA_URL}/api/chat", json=payload, timeout=900) as r:
            if r.status_code != 200:
                r.read()
                raise LLMError(f"Ollama returned {r.status_code}: {r.text[:200]}")
            for line in r.iter_lines():
                if not line:
                    continue
                msg = json.loads(line)
                if msg.get("error"):
                    raise LLMError(f"Ollama error: {msg['error']}")
                chunks.append(msg.get("message", {}).get("content", ""))
                if on_token:
                    on_token(len(chunks))
                if msg.get("done"):
                    break
    except httpx.ConnectError as e:
        raise LLMError(f"Can't reach Ollama at {config.OLLAMA_URL}. Is `ollama serve` running?") from e
    return "".join(chunks)


# ---------- Gemma via the Gemini API ----------

def _gemini_schema(schema: dict) -> dict:
    """JSON schema -> the Gemini API's OpenAPI-style schema (upper-case type names)."""
    out = {}
    for k, v in schema.items():
        if k == "type":
            out[k] = v.upper()
        elif k == "properties":
            out[k] = {name: _gemini_schema(p) for name, p in v.items()}
        elif k == "items":
            out[k] = _gemini_schema(v)
        else:
            out[k] = v
    return out


def _gemini_tools(tools: list[dict]) -> list[dict]:
    decls = []
    for t in tools:
        fn = t["function"]
        decl = {"name": fn["name"], "description": fn["description"]}
        if fn["parameters"].get("properties"):
            decl["parameters"] = _gemini_schema(fn["parameters"])
        decls.append(decl)
    return [{"functionDeclarations": decls}]


def _gemini_contents(messages: list) -> tuple[dict | None, list]:
    system, contents = None, []
    for m in messages:
        if m["role"] == "system":
            system = {"parts": [{"text": m["content"]}]}
            continue
        if m["role"] == "tool":
            role, parts = "user", [{"functionResponse": {"name": m["tool_name"], "response": {"result": m["content"]}}}]
        elif m["role"] == "assistant":
            # Replay the model's own parts verbatim: they carry thought signatures the API expects back.
            role, parts = "model", m.get("_gemini_parts") or [{"text": m["content"]}]
        else:
            role, parts = "user", [{"text": m["content"]}]
        if contents and contents[-1]["role"] == role:  # e.g. several tool results in one turn
            contents[-1]["parts"].extend(parts)
        else:
            contents.append({"role": role, "parts": parts})
    return system, contents


def _gemini(messages: list, temperature: float, tools: list[dict] | None = None, schema: dict | None = None) -> dict:
    if not config.GEMINI_API_KEY:
        raise LLMError("LLM_PROVIDER=gemma needs GEMINI_API_KEY (get one at https://aistudio.google.com/apikey).")
    system, contents = _gemini_contents(messages)
    body = {"contents": contents, "generationConfig": {"temperature": temperature}}
    if config.GEMMA_THINKING:
        body["generationConfig"]["thinkingConfig"] = {"thinkingLevel": config.GEMMA_THINKING}
    if system:
        body["systemInstruction"] = system
    if tools:
        body["tools"] = _gemini_tools(tools)
    if schema:
        body["generationConfig"].update(responseMimeType="application/json", responseSchema=_gemini_schema(schema))
    try:
        r = httpx.post(GEMINI_URL.format(model=config.GEMMA_MODEL), json=body, timeout=300,
                       headers={"x-goog-api-key": config.GEMINI_API_KEY})
    except httpx.HTTPError as e:
        raise LLMError(f"Can't reach the Gemini API: {e}") from e
    if r.status_code != 200:
        try:
            detail = r.json()["error"]["message"]
        except Exception:
            detail = r.text[:200]
        raise LLMError(f"Gemini API returned {r.status_code}: {detail}")
    data = r.json()
    candidates = data.get("candidates") or []
    if not candidates:
        raise LLMError(f"Gemini API returned no answer: {data.get('promptFeedback', data)}")
    parts = candidates[0].get("content", {}).get("parts") or []
    return {
        "content": "".join(p.get("text", "") for p in parts if not p.get("thought")),
        "tool_calls": [{"function": {"name": p["functionCall"]["name"], "arguments": p["functionCall"].get("args") or {}}}
                       for p in parts if "functionCall" in p],
        "_gemini_parts": parts,
        "_tokens": data.get("usageMetadata", {}).get("candidatesTokenCount", 0),
    }


# ---------- public API ----------

def chat(messages: list, tools: list[dict], temperature: float) -> dict:
    """One chat turn with tools available. Returns {"content", "tool_calls", ...} (Ollama shape)."""
    if config.LLM_PROVIDER == "gemma":
        return _gemini(messages, temperature, tools=tools)
    return _ollama_chat(messages, tools, temperature)


def generate_json(messages: list, schema: dict, temperature: float, on_token=None) -> str:
    """Generate a JSON document matching `schema`. `on_token(n)` reports progress."""
    if config.LLM_PROVIDER == "gemma":
        msg = _gemini(messages, temperature, schema=schema)
        if on_token:
            on_token(msg["_tokens"])
        # Strip a ```json fence in case the model adds one.
        return re.sub(r"^\s*```(?:json)?\s*|\s*```\s*$", "", msg["content"])
    return _ollama_json(messages, schema, temperature, on_token)
