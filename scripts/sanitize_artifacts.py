#!/usr/bin/env python3
"""Redact keys and OpenAI-compatible endpoint URLs from tracked artifacts."""

from __future__ import annotations

import argparse
import re
from pathlib import Path


TEXT_SUFFIXES = {
    ".cfg",
    ".csv",
    ".json",
    ".jsonl",
    ".log",
    ".md",
    ".txt",
}

PATTERNS = [
    (re.compile(r"sk-[A-Za-z0-9_\-]{16,}"), "sk-REDACTED"),
    (re.compile(r"tp-[A-Za-z0-9_\-]{16,}"), "tp-REDACTED"),
    (
        re.compile(
            r"/mnt/(?:data|volume|volume1)/[^\s\"')\]]*"
            r"orcaloca-django11999-disambiguation-stability"
        ),
        "[REPO_ROOT]",
    ),
    (re.compile(r"/home/jql/miniforge3"), "[CONDA_PREFIX]"),
    (re.compile(r"/home/jql"), "[HOME]"),
    (
        re.compile(r"https?://[A-Za-z0-9._:\-]+(?:/v[0-9])?/chat/completions"),
        "[OPENAI_COMPATIBLE_ENDPOINT]/chat/completions",
    ),
    (
        re.compile(r"https?://[A-Za-z0-9._:\-]+/v[0-9](?=[\"'\\s])"),
        "[OPENAI_COMPATIBLE_BASE_URL]",
    ),
]


def sanitize_file(path: Path) -> bool:
    if path.suffix not in TEXT_SUFFIXES:
        return False
    text = path.read_text(errors="ignore")
    new_text = text
    for pattern, replacement in PATTERNS:
        new_text = pattern.sub(replacement, new_text)
    if new_text != text:
        path.write_text(new_text)
        return True
    return False


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    artifact_root = args.root.resolve() / "artifacts"
    changed = []
    if artifact_root.exists():
        for path in artifact_root.rglob("*"):
            if path.is_file() and sanitize_file(path):
                changed.append(str(path.relative_to(args.root.resolve())))
    print(f"Sanitized {len(changed)} artifact files")


if __name__ == "__main__":
    main()
