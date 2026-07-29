#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SOURCE_ORCA="${SOURCE_ORCA:-$ROOT_DIR/source/OrcaLoca}"
PYTHON_BIN="${PYTHON_BIN:-python}"
INSTANCE_ID="${INSTANCE_ID:-django__django-11999}"
MODEL="${ORCALOCA_MODEL:-gpt-5.4-mini}"
MAX_TOKENS="${ORCALOCA_MAX_TOKENS:-4096}"
DATASET="${ORCALOCA_DATASET:-SWE-bench_common}"
SPLIT="${ORCALOCA_SPLIT:-test}"
TRIALS="${TRIALS:-5}"
RUN_GROUPS="${RUN_GROUPS:-standard no_disamb}"
WORK_ROOT="${WORK_ROOT:-$ROOT_DIR/work/django11999_stability}"
RESET_WARM_CONTAINERS="${RESET_WARM_CONTAINERS:-1}"

if [ -z "${OPENAI_API_KEY:-}" ]; then
  echo "ERROR: OPENAI_API_KEY is not set." >&2
  exit 1
fi

BASE_URL_SOURCE=""
BASE_URL_EFFECTIVE=""
for name in OPENAI_BASE_URL BASE_URL API_BASE_URL OPENAI_API_BASE; do
  value="${!name:-}"
  if [ -n "$value" ]; then
    BASE_URL_SOURCE="$name"
    BASE_URL_EFFECTIVE="$value"
    break
  fi
done

if [ -z "$BASE_URL_EFFECTIVE" ]; then
  echo "ERROR: OpenAI-compatible base URL is not set." >&2
  exit 1
fi

if [ ! -d "$SOURCE_ORCA" ]; then
  echo "ERROR: OrcaLoca source not found: $SOURCE_ORCA" >&2
  exit 1
fi

mkdir -p "$WORK_ROOT" "$ROOT_DIR/artifacts/django11999"

"$PYTHON_BIN" - <<PY
import json
import platform
import subprocess
from datetime import datetime, timezone
from pathlib import Path

root = Path("$ROOT_DIR")
meta = {
    "created_at_utc": datetime.now(timezone.utc).isoformat(),
    "instance_id": "$INSTANCE_ID",
    "dataset": "$DATASET",
    "split": "$SPLIT",
    "model": "$MODEL",
    "max_tokens": int("$MAX_TOKENS"),
    "trials_per_group": int("$TRIALS"),
    "container_mode": "one warm persistent container per group",
    "reset_warm_containers": bool(int("$RESET_WARM_CONTAINERS")),
    "run_groups": "$RUN_GROUPS".split(),
    "python_bin": "$PYTHON_BIN",
    "python_version": platform.python_version(),
    "base_url_source": "$BASE_URL_SOURCE",
    "base_url_present": bool("$BASE_URL_EFFECTIVE"),
    "api_key_present": True,
}
try:
    meta["git_source_commit"] = subprocess.check_output(
        ["git", "-C", "$SOURCE_ORCA", "rev-parse", "HEAD"],
        text=True,
        stderr=subprocess.DEVNULL,
    ).strip()
except Exception:
    meta["git_source_commit"] = "source copy without .git"
(root / "artifacts" / "django11999" / "experiment_metadata.json").write_text(
    json.dumps(meta, indent=2) + "\n"
)
print(json.dumps(meta, indent=2))
PY

prepare_worktree() {
  local group="$1"
  local trial="$2"
  local config_path="$3"
  local exp_dir="$WORK_ROOT/runs/$group/$trial"
  local orca_dir="$exp_dir/OrcaLoca"

  mkdir -p "$exp_dir"
  if [ ! -d "$orca_dir" ]; then
    rsync -a \
      --exclude '.git/' \
      --exclude '__pycache__/' \
      --exclude '*.pyc' \
      --exclude 'key.cfg' \
      --exclude 'log/' \
      --exclude 'output/' \
      "$SOURCE_ORCA/" "$orca_dir/"
  fi
  cp "$config_path" "$orca_dir/Orcar/search.cfg"

  umask 077
  {
    printf 'OPENAI_API_KEY=%s\n' "$OPENAI_API_KEY"
    printf 'OPENAI_BASE_URL=%s\n' "$BASE_URL_EFFECTIVE"
    printf 'BASE_URL=%s\n' "$BASE_URL_EFFECTIVE"
    printf 'API_BASE_URL=%s\n' "$BASE_URL_EFFECTIVE"
    printf 'OPENAI_API_BASE=%s\n' "$BASE_URL_EFFECTIVE"
  } > "$orca_dir/key.cfg"
  chmod 600 "$orca_dir/key.cfg"
}

run_trial() {
  local group="$1"
  local trial_num="$2"
  local trial
  trial="$(printf 'trial_%02d' "$trial_num")"
  local config_path
  local ctr
  local exp_dir="$WORK_ROOT/runs/$group/$trial"
  local orca_dir="$exp_dir/OrcaLoca"
  local log_file="$exp_dir/run_${group}_${trial}.log"
  local output_json="$orca_dir/output/$INSTANCE_ID/searcher_$INSTANCE_ID.json"

  case "$group" in
    standard)
      config_path="$ROOT_DIR/configs/search_standard.cfg"
      ;;
    no_disamb)
      config_path="$ROOT_DIR/configs/search_no_disamb.cfg"
      ;;
    *)
      echo "Unknown group: $group" >&2
      exit 1
      ;;
  esac

  ctr="orcar_django11999_${group}_warm_ctr"
  prepare_worktree "$group" "$trial" "$config_path"

  if [ -s "$output_json" ]; then
    echo "SKIP: $group $trial already has $output_json" | tee -a "$log_file"
    return
  fi

  if [ "$trial_num" = "1" ] && [ "$RESET_WARM_CONTAINERS" = "1" ]; then
    sudo -n docker rm -f "$ctr" >/dev/null 2>&1 || true
  fi

  echo "===== $group $trial =====" | tee -a "$log_file"
  echo "Instance: $INSTANCE_ID" | tee -a "$log_file"
  echo "Dataset: $DATASET / $SPLIT" | tee -a "$log_file"
  echo "Model: $MODEL" | tee -a "$log_file"
  echo "Max tokens: $MAX_TOKENS" | tee -a "$log_file"
  echo "Base URL source: ${BASE_URL_SOURCE:-none}" | tee -a "$log_file"

  (
    cd "$orca_dir"
    sudo -E env \
      HF_HOME="$exp_dir/hf" \
      HF_DATASETS_CACHE="$exp_dir/hf_datasets" \
      ORCAR_CACHE_DIR="$exp_dir/orcar_cache" \
      ORCALOCA_MAX_TOKENS="$MAX_TOKENS" \
      ORCAR_LLM_MAX_RETRY="${ORCAR_LLM_MAX_RETRY:-10}" \
      ORCAR_LLM_RETRY_DELAY="${ORCAR_LLM_RETRY_DELAY:-2}" \
      ORCAR_LLM_RETRY_DELAY_MAX="${ORCAR_LLM_RETRY_DELAY_MAX:-45}" \
      PYTHONPATH="$orca_dir:${PYTHONPATH:-}" \
      "$PYTHON_BIN" evaluation/run.py \
        -cfg "$orca_dir/key.cfg" \
        -m "$MODEL" \
        -d "$DATASET" \
        -s "$SPLIT" \
        -c "$ctr" \
        --final_stage search \
        --instance_ids "$INSTANCE_ID"
  ) 2>&1 | tee -a "$log_file"

  sudo chown -R "$(id -u):$(id -g)" "$exp_dir" || true

  if [ "$group" = "standard" ] && [ "$trial_num" = "1" ]; then
    if [ -d "$exp_dir/orcar_cache/django__django" ]; then
      PYTHONPATH="$orca_dir:${PYTHONPATH:-}" "$PYTHON_BIN" \
        "$ROOT_DIR/scripts/export_runtime_index.py" \
        --repo-path "$exp_dir/orcar_cache/django__django" \
        --log-dir "$orca_dir/log/$INSTANCE_ID" \
        --output-dir "$ROOT_DIR/artifacts/django11999/inverted_index" \
        --instance-id "$INSTANCE_ID"
    fi
  fi
}

for trial_num in $(seq 1 "$TRIALS"); do
  for group in $RUN_GROUPS; do
    run_trial "$group" "$trial_num"
    "$PYTHON_BIN" "$ROOT_DIR/scripts/summarize_django11999_trials.py" --root "$ROOT_DIR"
    "$PYTHON_BIN" "$ROOT_DIR/scripts/collect_trial_artifacts.py" --root "$ROOT_DIR"
    "$PYTHON_BIN" "$ROOT_DIR/scripts/sanitize_artifacts.py" --root "$ROOT_DIR"
  done
done

"$PYTHON_BIN" "$ROOT_DIR/scripts/summarize_django11999_trials.py" --root "$ROOT_DIR"
"$PYTHON_BIN" "$ROOT_DIR/scripts/collect_trial_artifacts.py" --root "$ROOT_DIR"
"$PYTHON_BIN" "$ROOT_DIR/scripts/sanitize_artifacts.py" --root "$ROOT_DIR"
