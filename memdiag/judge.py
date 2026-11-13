"""The judge layer: every model call memdiag makes goes through here.

    judge = OpenAICompatJudge("qwen2.5:7b", cache=DiskCache(".memdiag_cache"))
    r = judge.ask(load_prompt("extract_facts"), role="extractor", as_json=True, message="We moved to Denver.")
    r.data, r.cached, judge.usage.summary()

A Judge renders a versioned prompt, serves it from the disk cache when it can, parses JSON (retrying
once if the model returns invalid JSON), and records calls, cache hits, seconds and tokens per role.
Subclasses only implement `_complete`. Tests use FakeJudge, so they never call a model.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import time
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Optional, Union

from .prompt import Prompt


@dataclass
class JudgeResult:
    text: str
    data: Optional[dict]  # parsed JSON object when as_json=True and parsing succeeded
    model: str
    prompt_id: str
    prompt_version: int
    role: str
    cached: bool = False
    seconds: float = 0.0
    prompt_tokens: int = 0
    completion_tokens: int = 0


class Usage:
    """Calls, cache hits, seconds and tokens per role, for the cost line at the end of every run."""

    def __init__(self):
        self.by_role: dict[str, dict] = defaultdict(
            lambda: {"calls": 0, "cached": 0, "seconds": 0.0, "prompt_tokens": 0, "completion_tokens": 0})

    def add(self, r: JudgeResult) -> None:
        row = self.by_role[r.role]
        row["calls"] += 1
        row["cached"] += r.cached
        row["seconds"] += r.seconds
        row["prompt_tokens"] += r.prompt_tokens
        row["completion_tokens"] += r.completion_tokens

    def summary(self) -> str:
        lines = [f"{role:20s} {u['calls']:5d} calls ({u['cached']} cached) {u['seconds']:8.1f}s "
                 f"{u['prompt_tokens'] + u['completion_tokens']:9d} tokens" for role, u in sorted(self.by_role.items())]
        return "\n".join(lines) or "no model calls"


class DiskCache:
    """One JSON file per call, keyed by model, prompt id and version, rendered text and JSON mode."""

    def __init__(self, directory):
        self.dir = Path(directory)
        self.dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def key(model: str, prompt_id: str, version: int, text: str, as_json: bool) -> str:
        blob = json.dumps([model, prompt_id, version, text, as_json], ensure_ascii=False)
        return hashlib.sha256(blob.encode()).hexdigest()

    def get(self, key: str) -> Optional[dict]:
        path = self.dir / f"{key}.json"
        try:
            return json.loads(path.read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            return None

    def put(self, key: str, value: dict) -> None:
        # Write to a temp file and rename, so a crash never leaves a half-written entry.
        fd, tmp = tempfile.mkstemp(dir=self.dir, suffix=".tmp")
        with os.fdopen(fd, "w") as f:
            json.dump(value, f)
        os.replace(tmp, self.dir / f"{key}.json")


def parse_json(text: str) -> Optional[dict]:
    """A JSON object from model output, tolerating prose or code fences around it."""
    for candidate in (text, *re.findall(r"\{.*\}", text, re.S)):
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            return data
    return None


class Judge:
    model = "unknown"

    def __init__(self, cache: Optional[DiskCache] = None):
        self.cache = cache
        self.usage = Usage()

    def ask(self, prompt: Prompt, role: str = "", as_json: bool = False, **fields) -> JudgeResult:
        text = prompt.render(**fields)
        role = role or prompt.id
        key = DiskCache.key(self.model, prompt.id, prompt.version, text, as_json)
        hit = self.cache.get(key) if self.cache else None
        if hit is not None:
            result = JudgeResult(**{**hit, "role": role, "cached": True, "seconds": 0.0})
        else:
            start = time.time()
            out, tokens = self._complete(text, as_json, prompt.id)
            data = parse_json(out) if as_json else None
            if as_json and data is None:
                retry = (f"{text}\n\nYour previous reply was not a valid JSON object:\n{out[:500]}\n"
                         "Reply with one valid JSON object only.")
                out, more = self._complete(retry, as_json, prompt.id)
                data = parse_json(out)
                tokens = {k: tokens.get(k, 0) + more.get(k, 0) for k in ("prompt_tokens", "completion_tokens")}
            result = JudgeResult(out, data, self.model, prompt.id, prompt.version, role, False,
                                 round(time.time() - start, 3), tokens.get("prompt_tokens", 0),
                                 tokens.get("completion_tokens", 0))
            if self.cache and (data is not None or not as_json):  # never cache a failed parse
                self.cache.put(key, asdict(result))
        self.usage.add(result)
        return result

    def _complete(self, text: str, as_json: bool, prompt_id: str) -> tuple[str, dict]:
        """Return the model's reply and token counts ({"prompt_tokens": n, "completion_tokens": m})."""
        raise NotImplementedError


Response = Union[str, Callable[[str], str], list]


class FakeJudge(Judge):
    """Scripted replies by prompt id, for tests. A list is consumed in order; a callable gets the prompt text."""

    def __init__(self, responses: dict[str, Response], model: str = "fake", cache: Optional[DiskCache] = None):
        super().__init__(cache)
        self.model = model
        self.responses = {k: list(v) if isinstance(v, list) else v for k, v in responses.items()}
        self.calls: list[tuple[str, str]] = []

    def _complete(self, text, as_json, prompt_id):
        self.calls.append((prompt_id, text))
        r = self.responses[prompt_id]
        out = r.pop(0) if isinstance(r, list) else (r(text) if callable(r) else r)
        return out, {}


FAMILIES = ("qwen", "llama", "gpt", "claude", "gemini", "mistral", "phi", "gemma", "deepseek")


def model_family(model: str) -> Optional[str]:
    name = model.lower()
    return next((f for f in FAMILIES if f in name), None)


def same_family(a: str, b: str) -> bool:
    """True when two models share a family; a judge should not grade its own family's answers (D9)."""
    fa, fb = model_family(a), model_family(b)
    return fa is not None and fa == fb
