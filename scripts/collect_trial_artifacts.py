#!/usr/bin/env python3
"""Copy compact per-trial outputs/logs from work/ into tracked artifacts/."""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path


INSTANCE_ID = "django__django-11999"
FILES_TO_COPY = [
    "orcar_total.log",
    "action_history.log",
    "search_queue.log",
    "Orcar.search_agent.log",
    "Orcar.code_scorer.log",
    "Orcar.trace_analysis_agent.log",
    f"orcar_{INSTANCE_ID}.log",
]


def copy_if_exists(src: Path, dst: Path) -> None:
    if not src.exists():
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def latest_log_dir(orca_dir: Path) -> Path:
    """Return the newest OrcaLoca log directory for this instance."""
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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    root = args.root.resolve()
    runs_root = root / "work" / "django11999_stability" / "runs"
    artifact_root = root / "artifacts" / "django11999" / "runs"

    for group in ["standard", "no_disamb"]:
        group_dir = runs_root / group
        if not group_dir.exists():
            continue
        for trial_dir in sorted(group_dir.glob("trial_*")):
            if not trial_dir.is_dir():
                continue
            out_dir = artifact_root / group / trial_dir.name
            output_json = (
                trial_dir
                / "OrcaLoca"
                / "output"
                / INSTANCE_ID
                / f"searcher_{INSTANCE_ID}.json"
            )
            copy_if_exists(output_json, out_dir / "searcher_django__django-11999.json")
            log_dir = latest_log_dir(trial_dir / "OrcaLoca")
            for file_name in FILES_TO_COPY:
                copy_if_exists(log_dir / file_name, out_dir / "logs" / file_name)
            copy_if_exists(
                trial_dir / f"run_{group}_{trial_dir.name}.log",
                out_dir / f"run_{group}_{trial_dir.name}.log",
            )
    print(f"Collected artifacts under {artifact_root}")


if __name__ == "__main__":
    main()
