"""Versioned prompt files (memdiag/prompts/*.txt).

A prompt file is a small header, a line with `---`, then the template:

    id: extract_facts
    version: 1
    description: ...
    ---
    ... $message ...

Templates use string.Template placeholders, so JSON examples in the text need no escaping. Bump `version`
whenever the text changes: the judge cache and every Finding key on (id, version).
"""
from __future__ import annotations

from dataclasses import dataclass
from importlib import resources
from string import Template


@dataclass(frozen=True)
class Prompt:
    id: str
    version: int
    template: str
    description: str = ""

    def render(self, **fields) -> str:
        """Fill the template. A missing field raises KeyError, so a prompt is never sent half-filled."""
        return Template(self.template).substitute(**fields)


def parse_prompt(text: str) -> Prompt:
    head, sep, body = text.partition("\n---\n")
    if not sep:
        raise ValueError("prompt file needs a header, then a line with ---")
    meta = dict(line.split(":", 1) for line in head.strip().splitlines() if ":" in line)
    meta = {k.strip(): v.strip() for k, v in meta.items()}
    for key in ("id", "version"):
        if key not in meta:
            raise ValueError(f"prompt header is missing '{key}'")
    return Prompt(meta["id"], int(meta["version"]), body.strip("\n"), meta.get("description", ""))


def load_prompt(prompt_id: str) -> Prompt:
    path = resources.files("memdiag") / "prompts" / f"{prompt_id}.txt"
    prompt = parse_prompt(path.read_text())
    if prompt.id != prompt_id:
        raise ValueError(f"{path} declares id {prompt.id!r}, expected {prompt_id!r}")
    return prompt
