"""Prompts as YAML files under ``<root>/<name>/<version>.yaml``.

The content hash (template + declared inputs + metadata) is the immutable version id; the
human label (``v2``) is a name for it. ``name@v2`` and ``name@<hash prefix>`` both resolve.
Rendering uses Jinja2 with ``StrictUndefined`` so a missing variable is an error, not an empty
string silently sent to the model.
"""

from __future__ import annotations

import difflib
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from jinja2 import Environment, StrictUndefined, meta
from jinja2.exceptions import TemplateError, UndefinedError
from pydantic import BaseModel, Field

from opsloop.llm import estimate_tokens

_ENV = Environment(undefined=StrictUndefined, autoescape=False, keep_trailing_newline=True)
DEFAULT_FORBIDDEN = (
    "guaranteed return",
    "ignore previous instructions",
    "you are now",
    "as your financial adviser",
)


class PromptSpec(BaseModel):
    name: str
    version: str
    description: str = ""
    template: str
    inputs: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    changelog: list[str] = Field(default_factory=list)

    @property
    def content_hash(self) -> str:
        canonical = json.dumps(
            {"template": self.template, "inputs": self.inputs, "metadata": self.metadata},
            sort_keys=True,
            ensure_ascii=False,
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:12]

    @property
    def ref(self) -> str:
        return f"{self.name}@{self.version}"

    def render(self, variables: dict[str, Any]) -> str:
        try:
            return _ENV.from_string(self.template).render(**variables)
        except UndefinedError as exc:
            msg = f"{self.ref}: {exc.message}"
            raise KeyError(msg) from exc

    def declared_placeholders(self) -> set[str]:
        return set(meta.find_undeclared_variables(_ENV.parse(self.template)))


@dataclass(frozen=True, slots=True)
class PromptRef:
    name: str
    version: str | None  # label or hash prefix; None = the active version


def parse_ref(text: str) -> PromptRef:
    if "@" in text:
        name, version = text.split("@", 1)
        return PromptRef(name.strip(), version.strip().lstrip("@") or None)
    return PromptRef(text.strip(), None)


@dataclass(frozen=True, slots=True)
class LintFinding:
    level: str  # "error" | "warning"
    code: str
    message: str


class PromptRegistry:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    # ----- files ----------------------------------------------------------------------------

    def _path(self, name: str, version: str) -> Path:
        return self.root / name / f"{version}.yaml"

    def register(self, spec: PromptSpec, *, overwrite: bool = False) -> Path:
        path = self._path(spec.name, spec.version)
        if path.exists() and not overwrite:
            existing = self.get(spec.ref)
            if existing.content_hash != spec.content_hash:
                msg = (
                    f"{spec.ref} already registered with hash {existing.content_hash}; "
                    "bump the version label instead of editing a released prompt"
                )
                raise FileExistsError(msg)
            return path
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = spec.model_dump(mode="json")
        payload["content_hash"] = spec.content_hash
        path.write_text(
            yaml.safe_dump(payload, sort_keys=False, allow_unicode=True, width=100),
            encoding="utf-8",
        )
        return path

    def register_file(self, path: Path, *, overwrite: bool = False) -> PromptSpec:
        spec = self.load_file(path)
        self.register(spec, overwrite=overwrite)
        return spec

    @staticmethod
    def load_file(path: Path) -> PromptSpec:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        raw.pop("content_hash", None)
        return PromptSpec.model_validate(raw)

    def list_prompts(self, name: str | None = None) -> list[PromptSpec]:
        specs: list[PromptSpec] = []
        if not self.root.exists():
            return specs
        for name_dir in sorted(p for p in self.root.iterdir() if p.is_dir()):
            if name is not None and name_dir.name != name:
                continue
            for file in sorted(name_dir.glob("*.yaml")):
                specs.append(self.load_file(file))
        return specs

    def get(self, ref: str | PromptRef) -> PromptSpec:
        r = parse_ref(ref) if isinstance(ref, str) else ref
        if r.version is None:
            msg = f"prompt ref {r.name!r} has no version; use name@version or resolve the release"
            raise KeyError(msg)
        direct = self._path(r.name, r.version)
        if direct.exists():
            return self.load_file(direct)
        for spec in self.list_prompts(r.name):
            if spec.content_hash.startswith(r.version):
                return spec
        msg = f"prompt {r.name}@{r.version} not found under {self.root}"
        raise KeyError(msg)

    # ----- operations -----------------------------------------------------------------------

    def render(self, ref: str, variables: dict[str, Any]) -> str:
        return self.get(ref).render(variables)

    def diff(self, ref_a: str, ref_b: str) -> str:
        a, b = self.get(ref_a), self.get(ref_b)
        lines = difflib.unified_diff(
            a.template.splitlines(),
            b.template.splitlines(),
            fromfile=f"{a.ref} ({a.content_hash})",
            tofile=f"{b.ref} ({b.content_hash})",
            lineterm="",
        )
        meta_diff: list[str] = []
        for key in sorted({*a.metadata, *b.metadata}):
            if a.metadata.get(key) != b.metadata.get(key):
                meta_diff.append(
                    f"metadata.{key}: {a.metadata.get(key)!r} -> {b.metadata.get(key)!r}"
                )
        return "\n".join([*lines, *meta_diff])

    def lint(
        self,
        ref: str,
        *,
        sample_variables: dict[str, Any] | None = None,
        max_prompt_tokens: int | None = None,
        forbidden: tuple[str, ...] = DEFAULT_FORBIDDEN,
    ) -> list[LintFinding]:
        spec = self.get(ref)
        findings: list[LintFinding] = []
        try:
            placeholders = spec.declared_placeholders()
        except TemplateError as exc:
            return [LintFinding("error", "syntax_error", str(exc))]
        undeclared = sorted(placeholders - set(spec.inputs))
        unused = sorted(set(spec.inputs) - placeholders)
        for name in undeclared:
            findings.append(
                LintFinding("error", "undeclared_placeholder", f"{{{{ {name} }}}} is not in inputs")
            )
        for name in unused:
            findings.append(LintFinding("warning", "unused_input", f"input {name!r} never used"))
        for m in re.finditer(r"(?<!\{)\{(?!\{)[^{}\n]*\}(?!\})", spec.template):
            findings.append(
                LintFinding(
                    "warning",
                    "single_brace",
                    f"{m.group(0)!r} looks like an unrendered placeholder",
                )
            )
        budget = max_prompt_tokens or int(spec.metadata.get("max_prompt_tokens", 0) or 0)
        variables = sample_variables or {name: f"<{name}>" for name in spec.inputs}
        try:
            rendered = spec.render(variables)
        except (KeyError, TemplateError) as exc:
            findings.append(LintFinding("error", "render_failed", str(exc)))
            rendered = spec.template
        tokens = estimate_tokens(rendered)
        if budget and tokens > budget:
            findings.append(
                LintFinding("error", "token_budget", f"~{tokens} tokens exceeds budget {budget}")
            )
        lowered = spec.template.lower()
        for phrase in (*forbidden, *spec.metadata.get("forbidden_phrases", [])):
            if phrase.lower() in lowered:
                findings.append(LintFinding("error", "forbidden_phrase", f"contains {phrase!r}"))
        return findings
