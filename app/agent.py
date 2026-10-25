"""A minimal tool-calling agent loop on the open-weight LLM (local Ollama or Gemma, see llm.py).

The model decides which tool to call; Python runs it and feeds the result back, until the model
answers in plain text or the step budget runs out.
"""
import json
import re
from dataclasses import dataclass, field
from typing import Callable

from . import llm


class AgentError(RuntimeError):
    pass


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict  # JSON schema for the arguments
    fn: Callable[..., object]

    def spec(self) -> dict:
        return {"type": "function", "function": {
            "name": self.name, "description": self.description, "parameters": self.parameters,
        }}


def params(required: list[str] | None = None, **props: dict) -> dict:
    """Shorthand for a JSON-schema object: params(query={"type": "string", "description": ...})."""
    return {"type": "object", "properties": props, "required": required if required is not None else list(props)}


@dataclass
class AgentResult:
    answer: str
    trace: list[dict] = field(default_factory=list)  # one entry per tool call: tool, args, result
    steps: int = 0


def _tool_calls(message: dict) -> list[tuple[str, dict]]:
    calls = []
    for c in message.get("tool_calls") or []:
        fn = c.get("function", {})
        args = fn.get("arguments") or {}
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except json.JSONDecodeError:
                args = {}
        calls.append((fn.get("name", ""), args))
    if calls:
        return calls
    # Small models sometimes write the call as text instead of using the tool-call channel.
    for m in re.finditer(r"\{[^{}]*\"name\"\s*:\s*\"(\w+)\"[^{}]*\"arguments\"\s*:\s*(\{[^{}]*\})[^{}]*\}",
                         message.get("content") or ""):
        try:
            calls.append((m.group(1), json.loads(m.group(2))))
        except json.JSONDecodeError:
            pass
    return calls


def run(system: str, messages: list[dict], tools: list[Tool], max_steps: int = 8,
        temperature: float = 0.1, on_step: Callable[[dict], None] | None = None,
        stop_tool: str | None = None) -> AgentResult:
    """Run the agent loop. `on_step(entry)` is called after every tool call (for live progress).

    If `stop_tool` is given, calling that tool ends the run and its result becomes the answer.
    """
    by_name = {t.name: t for t in tools}
    specs = [t.spec() for t in tools]
    convo = [{"role": "system", "content": system}, *messages]
    result = AgentResult(answer="")
    for step in range(max_steps):
        result.steps = step + 1
        try:
            msg = llm.chat(convo, specs, temperature)
        except llm.LLMError as e:
            raise AgentError(str(e)) from e
        calls = _tool_calls(msg)
        if not calls:
            result.answer = (msg.get("content") or "").strip()
            return result
        convo.append({**msg, "role": "assistant", "content": msg.get("content") or "",
                      "tool_calls": msg.get("tool_calls") or []})
        for name, args in calls:
            tool = by_name.get(name)
            if tool is None:
                output = f"Error: unknown tool {name!r}. Available: {', '.join(by_name)}."
            else:
                try:
                    output = tool.fn(**args)
                except TypeError as e:
                    output = f"Error: bad arguments for {name}: {e}"
                except Exception as e:  # tool failures go back to the model so it can recover
                    output = f"Error: {e}"
            text = output if isinstance(output, str) else json.dumps(output, ensure_ascii=False)
            entry = {"tool": name, "args": args, "result": text[:600]}
            result.trace.append(entry)
            if on_step:
                on_step(entry)
            convo.append({"role": "tool", "tool_name": name, "content": text})
            if name == stop_tool:
                result.answer = text
                return result
    result.answer = "I ran out of steps before finishing. Try asking a narrower question."
    return result
