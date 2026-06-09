"""
Pine Script v5 compatibility preprocessor.

Normalises TradingView-style source before parsing:
  - Strips //@version=N directives
  - Strips type annotations from assignments (float, int, series, etc.)
  - Normalises line endings
"""
from __future__ import annotations

import re

_VERSION_RE = re.compile(r"^\s*//@version\s*=\s*\d+\s*$", re.MULTILINE)

_TYPED_ASSIGN_RE = re.compile(
    r"^(\s*)"
    r"(?:(var|varip)\s+)?"
    r"(?:(?:series|simple|const|input)\s+)?"
    r"(?:float|int|bool|string|color|line|label|box|table|array|matrix|map|chart|tick)\s+"
    r"([A-Za-z_][A-Za-z0-9_]*)\s*=",
    re.MULTILINE,
)


def preprocess(source: str) -> str:
    """Return Pine source ready for the Tradin DSL parser."""
    text = source.replace("\r\n", "\n").replace("\r", "\n")
    text = _VERSION_RE.sub("", text)

    def _strip_types(match: re.Match[str]) -> str:
        indent, var_mod, name = match.group(1), match.group(2), match.group(3)
        prefix = f"{var_mod} " if var_mod else ""
        return f"{indent}{prefix}{name} ="

    text = _TYPED_ASSIGN_RE.sub(_strip_types, text)
    return text.strip()
