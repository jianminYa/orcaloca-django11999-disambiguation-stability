#!/usr/bin/env python3
"""Export OrcaLoca's runtime duplicate-key inverted index for one repo checkout."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from Orcar.search.build_graph import RepoGraph


FOCUSED_QUERIES = [
    "Field",
    "ModelBase",
    "contribute_to_class",
    "add_to_class",
    "_prepare",
    "__new__",
    "get_FOO_display",
    "_get_FIELD_display",
]


def serialize_value(value) -> dict:
    return {
        "type": value.type,
        "file_path": value.file_path,
        "class_name": value.class_name,
    }


def parse_disambiguation_blocks(log_dir: Path) -> list[dict]:
    log_path = log_dir / "orcar_total.log"
    if not log_path.exists():
        return []
    text = log_path.read_text(errors="ignore")
    blocks = re.findall(
        r"<Disambiguation>(?:\\n|\n)(.*?)(?:\\n|\n)</Disambiguation>",
        text,
        re.S,
    )
    events: list[dict] = []
    for idx, block in enumerate(blocks, start=1):
        normalized_block = block.replace("\\n", "\n")
        query = None
        for pattern in [
            r"query ([A-Za-z_][A-Za-z_0-9]*)",
            r"file ([^.\s]+(?:\.py)?)",
            r"class:?\s+([A-Za-z_][A-Za-z_0-9]*)",
        ]:
            match = re.search(pattern, normalized_block)
            if match:
                query = match.group(1)
                break
        candidates = []
        candidate_pattern = re.compile(
            r"Possible Location (\d+):\n"
            r"File Path: ([^\n]+)\n"
            r"(?:Containing Class: ([^\n]+)\n)?",
            re.S,
        )
        for candidate in candidate_pattern.finditer(normalized_block):
            candidates.append(
                {
                    "rank_in_message": int(candidate.group(1)),
                    "file_path": candidate.group(2).strip(),
                    "class_name": (candidate.group(3) or "").strip() or None,
                }
            )
        events.append(
            {
                "event_index": idx,
                "query": query,
                "candidate_count": len(candidates),
                "candidates": candidates,
                "raw_message": normalized_block.strip(),
            }
        )
    return events


def parse_selected_disambiguation_actions(log_dir: Path) -> list[str]:
    path = log_dir / "action_history.log"
    if not path.exists():
        return []
    return [
        line.strip()
        for line in path.read_text(errors="ignore").splitlines()
        if "Disambiguation:" in line
    ]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-path", required=True, type=Path)
    parser.add_argument("--log-dir", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--instance-id", default="django__django-11999")
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    graph = RepoGraph(repo_path=str(args.repo_path))
    index = graph.inverted_index.index

    rows = []
    type_counts = Counter()
    candidate_counts = []
    for key in sorted(index):
        values = [serialize_value(value) for value in index[key]]
        rows.append({"key": key, "candidate_count": len(values), "candidates": values})
        candidate_counts.append(len(values))
        for value in values:
            type_counts[value["type"]] += 1

    jsonl_path = args.output_dir / "django_duplicate_inverted_index.jsonl"
    with jsonl_path.open("w") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    focused = {
        query: {
            "present_after_singleton_pruning": query in index,
            "candidate_count": len(index.get(query, [])),
            "candidates": [serialize_value(value) for value in index.get(query, [])],
        }
        for query in FOCUSED_QUERIES
    }
    (args.output_dir / "django11999_focused_queries.json").write_text(
        json.dumps(focused, indent=2, ensure_ascii=False) + "\n"
    )

    events = parse_disambiguation_blocks(args.log_dir)
    with (args.output_dir / "django11999_disambiguation_events.jsonl").open("w") as handle:
        for event in events:
            handle.write(json.dumps(event, ensure_ascii=False) + "\n")

    selected_actions = parse_selected_disambiguation_actions(args.log_dir)
    (args.output_dir / "django11999_selected_disambiguation_actions.txt").write_text(
        "\n".join(selected_actions) + ("\n" if selected_actions else "")
    )

    stats = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "instance_id": args.instance_id,
        "repo_path_basename": args.repo_path.name,
        "build_mode": "runtime rebuild from checked-out repository via RepoGraph(repo_path)",
        "singleton_keys_removed": True,
        "duplicate_key_count": len(rows),
        "duplicate_candidate_total": sum(candidate_counts),
        "max_candidate_count": max(candidate_counts) if candidate_counts else 0,
        "candidate_type_counts": dict(sorted(type_counts.items())),
        "export_files": {
            "full_duplicate_index_jsonl": str(jsonl_path.relative_to(args.output_dir.parent.parent.parent)),
            "focused_queries_json": "artifacts/django11999/inverted_index/django11999_focused_queries.json",
            "disambiguation_events_jsonl": "artifacts/django11999/inverted_index/django11999_disambiguation_events.jsonl",
            "selected_actions_txt": "artifacts/django11999/inverted_index/django11999_selected_disambiguation_actions.txt",
        },
    }
    (args.output_dir / "django_duplicate_index_stats.json").write_text(
        json.dumps(stats, indent=2, ensure_ascii=False) + "\n"
    )
    print(json.dumps(stats, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
