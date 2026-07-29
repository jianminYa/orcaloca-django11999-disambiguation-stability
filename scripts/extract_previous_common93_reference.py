#!/usr/bin/env python3
"""Extract compact django__django-11999 evidence from the prior Common93 run."""

from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path


INSTANCE_ID = "django__django-11999"
GOLD_FILE = "django/db/models/fields/__init__.py"
GOLD_FUNCTION = "django/db/models/fields/__init__.py:Field.contribute_to_class"


def read(path: Path) -> str:
    return path.read_text(errors="ignore") if path.exists() else ""


def load_bug_locations(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return json.loads(path.read_text()).get("bug_locations", [])


def normalize_file(path: str) -> str:
    return path[1:] if path.startswith("/") else path


def function_keys(locations: list[dict]) -> set[str]:
    keys = set()
    for loc in locations:
        file_path = normalize_file(loc.get("file_path", ""))
        class_name = loc.get("class_name", "")
        method_name = loc.get("method_name", "")
        if class_name and method_name:
            keys.add(f"{file_path}:{class_name}.{method_name}")
        elif class_name:
            keys.add(f"{file_path}:{class_name}")
        elif method_name:
            keys.add(f"{file_path}:{method_name}")
    return keys


def file_keys(locations: list[dict]) -> set[str]:
    return {normalize_file(loc.get("file_path", "")) for loc in locations if loc.get("file_path")}


def excerpt_around(text: str, marker: str, radius: int = 1100) -> str:
    idx = text.find(marker)
    if idx < 0:
        return ""
    start = max(0, idx - radius)
    end = min(len(text), idx + len(marker) + radius)
    return text[start:end].strip()


def action_lines(text: str, pattern: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if pattern in line]


def sanitize(text: str) -> str:
    text = re.sub(r"sk-[A-Za-z0-9_\-]{16,}", "sk-REDACTED", text)
    text = re.sub(r"tp-[A-Za-z0-9_\-]{16,}", "tp-REDACTED", text)
    text = re.sub(
        r"https?://[A-Za-z0-9._:\-]+(?:/v[0-9])?/chat/completions",
        "[OPENAI_COMPATIBLE_ENDPOINT]/chat/completions",
        text,
    )
    text = re.sub(
        r"https?://[A-Za-z0-9._:\-]+/v[0-9](?=[\"'\s])",
        "[OPENAI_COMPATIBLE_BASE_URL]",
        text,
    )
    return text


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument(
        "--common93-root",
        type=Path,
        default=Path(os.environ["COMMON93_REFERENCE_ROOT"])
        if os.environ.get("COMMON93_REFERENCE_ROOT")
        else None,
    )
    args = parser.parse_args()

    root = args.root.resolve()
    if args.common93_root is None:
        raise SystemExit(
            "Set COMMON93_REFERENCE_ROOT or pass --common93-root to extract "
            "the optional prior Common93 reference."
        )
    common_root = args.common93_root.resolve()
    artifact_root = root / "artifacts" / "django11999" / "previous_common93_reference"
    artifact_root.mkdir(parents=True, exist_ok=True)

    summary: dict[str, object] = {
        "source_artifact": "prior local Common93 disambiguation-ablation artifact export",
        "instance_id": INSTANCE_ID,
        "gold_file": GOLD_FILE,
        "gold_function": GOLD_FUNCTION,
        "groups": {},
    }

    for group in ["standard", "no_disamb"]:
        output_path = (
            common_root
            / "artifacts"
            / "common93"
            / "outputs"
            / group
            / INSTANCE_ID
            / f"searcher_{INSTANCE_ID}.json"
        )
        log_dir = common_root / "artifacts" / "common93" / "logs" / group / INSTANCE_ID
        action_history = read(log_dir / "action_history.log")
        orcar_total = read(log_dir / "orcar_total.log")
        locations = load_bug_locations(output_path)
        summary["groups"][group] = {
            "bug_locations": locations,
            "file_match": GOLD_FILE in file_keys(locations),
            "function_match": GOLD_FUNCTION in function_keys(locations),
            "disambiguation_action_lines": action_lines(action_history, "Disambiguation:"),
            "contribute_to_class_action_lines": action_lines(action_history, "contribute_to_class"),
        }

        excerpt = ""
        if group == "standard":
            excerpt = excerpt_around(action_history, "Disambiguation:")
        else:
            excerpt = excerpt_around(orcar_total, "Multiple matched callables found about query contribute_to_class")
        (artifact_root / f"{group}_key_excerpt.txt").write_text(sanitize(excerpt) + "\n")

    (artifact_root / "old_single_run_summary.json").write_text(
        sanitize(json.dumps(summary, indent=2, ensure_ascii=False)) + "\n"
    )
    print(f"Wrote {artifact_root}")


if __name__ == "__main__":
    main()
