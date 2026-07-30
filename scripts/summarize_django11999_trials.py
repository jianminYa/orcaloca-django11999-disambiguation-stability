#!/usr/bin/env python3
"""Summarize repeated django__django-11999 localization trials."""

from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path


INSTANCE_ID = "django__django-11999"
GOLD_FILE = "django/db/models/fields/__init__.py"
GOLD_FUNCTION = "django/db/models/fields/__init__.py:Field.contribute_to_class"


def normalize_file(path: str) -> str:
    return path[1:] if path.startswith("/") else path


def extract_model_sets(output_path: Path) -> tuple[set[str], set[str], list[dict]]:
    if not output_path.exists():
        return set(), set(), []
    data = json.loads(output_path.read_text())
    locations = data.get("bug_locations", [])
    files: set[str] = set()
    funcs: set[str] = set()
    for loc in locations:
        file_path = normalize_file(loc.get("file_path", ""))
        class_name = loc.get("class_name", "")
        method_name = loc.get("method_name", "")
        if file_path:
            files.add(file_path)
        if class_name and method_name:
            funcs.add(f"{file_path}:{class_name}")
            funcs.add(f"{file_path}:{class_name}.{method_name}")
        elif class_name:
            funcs.add(f"{file_path}:{class_name}")
        elif method_name:
            funcs.add(f"{file_path}:{method_name}")
    return files, funcs, locations


def count_api_errors(text: str) -> dict:
    patterns = {
        "retry_messages": r"OpenAI-compatible .* retry",
        "429": r"(?<!\d)429(?!\d)",
        "502": r"(?<!\d)502(?!\d)",
        "503": r"(?<!\d)503(?!\d)",
        "timeout": r"(?i)timeout|timed out",
        "openai_error": r"OpenAIError|APIConnectionError|APIStatusError|RateLimitError",
    }
    return {name: len(re.findall(pattern, text)) for name, pattern in patterns.items()}


def token_sum(log_text: str) -> dict:
    input_tokens = 0
    output_tokens = 0
    for match in re.finditer(r"in_token_cnt=(\d+), out_token_cnt=(\d+)", log_text):
        input_tokens += int(match.group(1))
        output_tokens += int(match.group(2))
    for match in re.finditer(
        r"Total cnt\s*: in\s+(\d+) tokens, out\s+(\d+) tokens", log_text
    ):
        input_tokens += int(match.group(1))
        output_tokens += int(match.group(2))
    return {
        "input_tokens_logged": input_tokens,
        "output_tokens_logged": output_tokens,
        "total_tokens_logged": input_tokens + output_tokens,
    }


def latest_log_dir(orca_dir: Path) -> Path:
    """Return the newest OrcaLoca log directory for this instance.

    OrcaLoca may create log_1, log_2, ... when a trial internally restarts.
    The final search log can therefore live outside the initial log/ tree.
    """
    candidates = []
    for base in sorted(orca_dir.glob("log*")):
        inst_dir = base / INSTANCE_ID
        if inst_dir.is_dir():
            total_log = inst_dir / "orcar_total.log"
            mtime = total_log.stat().st_mtime if total_log.exists() else inst_dir.stat().st_mtime
            candidates.append((mtime, inst_dir))
    if candidates:
        return max(candidates, key=lambda item: item[0])[1]
    return orca_dir / "log" / INSTANCE_ID


def extract_disambiguation_blocks(text: str) -> list[str]:
    # OrcaLoca logs ChatMessage reprs, so newlines inside <Disambiguation>
    # often appear as literal "\\n" rather than real newline characters.
    pattern = re.compile(
        r"<Disambiguation>(?:\\n|\n)(.*?)(?:\\n|\n)</Disambiguation>",
        re.S,
    )
    return [match.strip() for match in pattern.findall(text)]


def extract_ambiguous_search_blocks(text: str) -> list[str]:
    pattern = re.compile(
        r"<AmbiguousSearch>(?:\\n|\n)(.*?)(?:\\n|\n)</AmbiguousSearch>",
        re.S,
    )
    return [match.strip() for match in pattern.findall(text)]


def summarize_trial(root: Path, group: str, trial: str) -> dict:
    trial_dir = root / "work" / "django11999_stability" / "runs" / group / trial
    orca_dir = trial_dir / "OrcaLoca"
    output_path = orca_dir / "output" / INSTANCE_ID / f"searcher_{INSTANCE_ID}.json"
    log_dir = latest_log_dir(orca_dir)
    total_log = log_dir / "orcar_total.log"
    action_log = log_dir / "action_history.log"
    search_log = log_dir / "Orcar.search_agent.log"

    files, funcs, locations = extract_model_sets(output_path)
    total_text = total_log.read_text(errors="ignore") if total_log.exists() else ""
    action_text = action_log.read_text(errors="ignore") if action_log.exists() else ""
    run_log = trial_dir / f"run_{group}_{trial}.log"
    run_text = run_log.read_text(errors="ignore") if run_log.exists() else ""

    disamb_blocks = extract_disambiguation_blocks(total_text)
    ambiguous_blocks = extract_ambiguous_search_blocks(total_text)
    selected_lines = [line for line in action_text.splitlines() if "Disambiguation:" in line]
    completion_present = "bug_locations" in (output_path.read_text(errors="ignore") if output_path.exists() else "")

    row = {
        "group": group,
        "trial": trial,
        "completed": output_path.exists(),
        "json_has_bug_locations": completion_present,
        "file_match": GOLD_FILE in files,
        "function_match": GOLD_FUNCTION in funcs,
        "model_files": sorted(files),
        "model_functions": sorted(funcs),
        "model_locations": locations,
        "disambiguation_message_count": len(disamb_blocks),
        "ambiguous_search_message_count": len(ambiguous_blocks),
        "selected_disambiguation_action_count": len(selected_lines),
        "selected_disambiguation_actions": selected_lines,
        "api_errors": count_api_errors(total_text + "\n" + run_text),
        "token_count": token_sum(total_text),
        "log_paths": {
            "output_json": str(output_path.relative_to(root)) if output_path.exists() else "",
            "orcar_total": str(total_log.relative_to(root)) if total_log.exists() else "",
            "action_history": str(action_log.relative_to(root)) if action_log.exists() else "",
            "search_agent": str(search_log.relative_to(root)) if search_log.exists() else "",
        },
    }
    return row


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    root = args.root.resolve()

    rows = []
    runs_root = root / "work" / "django11999_stability" / "runs"
    groups = [path.name for path in sorted(runs_root.iterdir()) if path.is_dir()] if runs_root.exists() else []
    for group in groups:
        group_dir = runs_root / group
        for trial_dir in sorted(group_dir.glob("trial_*")):
            if trial_dir.is_dir():
                rows.append(summarize_trial(root, group, trial_dir.name))

    artifact_dir = root / "artifacts" / "django11999"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    summary = {
        "instance_id": INSTANCE_ID,
        "gold_file": GOLD_FILE,
        "gold_function": GOLD_FUNCTION,
        "trial_count": len(rows),
        "by_group": {},
        "trials": rows,
    }
    for group in groups:
        group_rows = [row for row in rows if row["group"] == group]
        if not group_rows:
            continue
        summary["by_group"][group] = {
            "completed": sum(row["completed"] for row in group_rows),
            "file_match": sum(row["file_match"] for row in group_rows),
            "function_match": sum(row["function_match"] for row in group_rows),
            "total": len(group_rows),
            "input_tokens_logged": sum(
                row["token_count"]["input_tokens_logged"] for row in group_rows
            ),
            "output_tokens_logged": sum(
                row["token_count"]["output_tokens_logged"] for row in group_rows
            ),
            "total_tokens_logged": sum(
                row["token_count"]["total_tokens_logged"] for row in group_rows
            ),
            "selected_disambiguation_actions": sum(
                row["selected_disambiguation_action_count"] for row in group_rows
            ),
            "disambiguation_messages": sum(
                row["disambiguation_message_count"] for row in group_rows
            ),
            "ambiguous_search_messages": sum(
                row["ambiguous_search_message_count"] for row in group_rows
            ),
            "api_retry_messages": sum(
                row["api_errors"]["retry_messages"] for row in group_rows
            ),
        }
    (artifact_dir / "trial_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n"
    )

    csv_path = artifact_dir / "trial_summary.csv"
    with csv_path.open("w", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            lineterminator="\n",
            fieldnames=[
                "group",
                "trial",
                "completed",
                "file_match",
                "function_match",
                "disambiguation_message_count",
                "ambiguous_search_message_count",
                "selected_disambiguation_action_count",
                "model_files",
                "model_functions",
            ],
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "group": row["group"],
                    "trial": row["trial"],
                    "completed": row["completed"],
                    "file_match": row["file_match"],
                    "function_match": row["function_match"],
                    "disambiguation_message_count": row["disambiguation_message_count"],
                    "ambiguous_search_message_count": row[
                        "ambiguous_search_message_count"
                    ],
                    "selected_disambiguation_action_count": row[
                        "selected_disambiguation_action_count"
                    ],
                    "model_files": ";".join(row["model_files"]),
                    "model_functions": ";".join(row["model_functions"]),
                }
            )
    print(json.dumps(summary["by_group"], indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
