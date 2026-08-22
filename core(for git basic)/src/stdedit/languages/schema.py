r"""
schema.py — token-rule JSON schema + language detection. OWNER: Person C.

Phase 1 target: define this schema + one working language (Python).
Phase 2 target: 6+ languages (Python, JS/TS, HTML/CSS, JSON, YAML,
                 Markdown, shell) + detection by file extension.

Suggested rule shape (regex-based, `re` from stdlib only, per STDLIB.md
substitution pygments -> re):

    LANGUAGES = {
        "python": {
            "extensions": [".py"],
            "rules": [
                # (token_type, regex)
                ("comment", r"#.*$"),
                ("string",  r"(\"\"\".*?\"\"\"|'''.*?'''|\".*?\"|'.*?')"),
                ("keyword", r"\b(def|class|if|elif|else|for|while|return|import|from|as|with|try|except|finally|raise|yield|lambda|pass|break|continue|and|or|not|in|is|None|True|False)\b"),
                ("number",  r"\b\d+(\.\d+)?\b"),
            ],
        },
    }

tokenize(line, language) should return a list of (start, end, token_type)
spans so tui.py can map them to curses color pairs.
"""

from __future__ import annotations

import re
from typing import Dict, List, Tuple

TokenSpan = Tuple[int, int, str]  # start, end, token_type

LANGUAGES: Dict[str, dict] = {
    "plaintext": {"extensions": [], "rules": []},
    "python": {
        "extensions": [".py", ".pyw"],
        "rules": [
            # Order matters: earlier rules win at the same start position.
            ("comment", r"#.*"),
            ("string", r"(\"\"\".*?\"\"\"|'''.*?'''|\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*')"),
            (
                "keyword",
                r"\b(?:def|class|if|elif|else|for|while|return|import|from|as|"
                r"with|try|except|finally|raise|yield|lambda|pass|break|continue|"
                r"and|or|not|in|is|None|True|False|global|nonlocal|assert|del|"
                r"async|await)\b",
            ),
            ("number", r"\b\d+(?:\.\d+)?\b"),
        ],
    },
}

# Precompiled per-language matchers, built lazily from LANGUAGES so
# editing the table above is enough — no separate place to keep in sync.
_COMPILED: Dict[str, "re.Pattern"] = {}


def _compiled_pattern(language: str):
    if language not in _COMPILED:
        rules = LANGUAGES.get(language, {}).get("rules", [])
        if not rules:
            _COMPILED[language] = None
        else:
            combined = "|".join(f"(?P<{name}>{pattern})" for name, pattern in rules)
            _COMPILED[language] = re.compile(combined)
    return _COMPILED[language]


def detect_language(filename: str) -> str:
    for name, spec in LANGUAGES.items():
        if any(filename.endswith(ext) for ext in spec.get("extensions", [])):
            return name
    return "plaintext"


def tokenize(line: str, language: str) -> List[TokenSpan]:
    pattern = _compiled_pattern(language)
    if pattern is None:
        return []
    spans: List[TokenSpan] = []
    for match in pattern.finditer(line):
        token_type = match.lastgroup
        spans.append((match.start(), match.end(), token_type))
    return spans
