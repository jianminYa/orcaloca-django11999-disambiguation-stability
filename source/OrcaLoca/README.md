# Patched OrcaLoca Source Snapshot

This directory is the patched OrcaLoca source tree used by the focused
`django__django-11999` disambiguation stability study in this repository.

For the experiment report, parameters, results, and artifact guide, start from
the repository-level README:

```text
../../README.md
```

## What This Source Tree Contains

| Path | Source | Notes |
| --- | --- | --- |
| `Orcar/` | Upstream OrcaLoca | Patched for OpenAI-compatible base URLs, retry behavior, nonstandard GPT-style model names, Common/Verified dataset loading, and a small environment install fallback. |
| `evaluation/` | Upstream OrcaLoca | Patched so `evaluation/run.py` can use `ORCALOCA_MAX_TOKENS`. |
| `artifact/`, `dataset/`, `tests/`, `cli.py`, `pyproject.toml` | Upstream OrcaLoca | Kept from the experiment checkout unless listed as patched below. |
| `third_party/Agentless/` | Vendored upstream Agentless | Included because earlier reproduction work used the same patched source snapshot for repair experiments. This focused study uses only OrcaLoca localization artifacts. |
| `patches/` | Local reproduction notes | Patch files from the earlier OpenAI-compatible reproduction work. The relevant source changes are already applied. |

Large runtime artifacts are intentionally excluded from this source tree:
API keys, local `key.cfg`, Docker images, conda environments, Hugging Face
cache, SWE-bench evaluation cache, and run outputs.

## Main Local Changes

OrcaLoca changes:

- `Orcar/gen_config.py`
  - reads OpenAI-compatible base URL from `OPENAI_BASE_URL`, `BASE_URL`,
    `API_BASE_URL`, or `OPENAI_API_BASE`;
  - keeps API keys in environment/config only;
  - supports GPT-style model names used by OpenAI-compatible backends;
  - adds retry handling for transient OpenAI-compatible API errors.
- `Orcar/load_cache_dataset.py`
  - supports the `SWE-bench_common` loader used in this experiment;
  - also supports Lite/Verified difference splits used during related checks.
- `Orcar/environment/benchmark.py`
  - includes a fallback from editable install to non-editable install for old
    projects that do not support `pip install -e .`.
- `evaluation/run.py`
  - reads `ORCALOCA_MAX_TOKENS`, defaulting to `4096`.
- `artifact/parse_output.py`
  - adds a `gdown` compatibility fallback for downloading golden localization
    metadata.

Agentless changes kept in this source snapshot:

- OpenAI-compatible and Anthropic-compatible base URL support.
- OrcaLoca-to-Agentless repair compatibility patches from the earlier
  resolved-rate reproduction work.

These Agentless patches are retained for provenance and reuse, but they are not
needed to reproduce the localization-only stability study reported here.

## API Configuration

Do not commit secrets. Configure keys through environment variables or a local
untracked `key.cfg`.

OpenAI-compatible backend:

```bash
export OPENAI_API_KEY=...
export OPENAI_BASE_URL=https://example-compatible-endpoint/v1
```

The OpenAI-compatible base URL priority is:

```text
OPENAI_BASE_URL > BASE_URL > API_BASE_URL > OPENAI_API_BASE
```

## Minimal Setup

```bash
conda create -n orca python=3.10 -y
conda activate orca
python -m pip install -U pip setuptools wheel
pip install -e .
docker pull hejiaz/swe-agent:latest
```

## django__django-11999 Stability Reproduction

Run the repository-level script instead of invoking this source tree directly:

```bash
cd ../..
scripts/run_django11999_stability_experiment.sh
```

The two experiment configs are:

```text
configs/search_standard.cfg
configs/search_no_disamb.cfg
```

## Upstream Projects

- OrcaLoca: https://github.com/fishmingyu/OrcaLoca
- Agentless: https://github.com/OpenAutoCoder/Agentless
- SWE-bench: https://github.com/SWE-bench/SWE-bench

## License

This source snapshot follows the licenses of the upstream projects included in
the tree.
