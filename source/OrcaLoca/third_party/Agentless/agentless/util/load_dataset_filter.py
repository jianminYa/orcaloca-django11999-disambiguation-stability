import json
import os

from datasets import load_dataset as _load_dataset


def load_dataset(*args, **kwargs):
    target_inst_ids_path = os.environ.get("AGENTLESS_TARGET_INST_IDS")
    if target_inst_ids_path == "":
        return _load_dataset(*args, **kwargs)

    # Check existence of target_inst_ids.json at repo root, unless an explicit
    # target id file is provided for a non-default dataset/run.
    if target_inst_ids_path is None:
        target_inst_ids_path = "target_inst_ids.json"

    if not os.path.exists(target_inst_ids_path):
        return _load_dataset(*args, **kwargs)

    with open(target_inst_ids_path) as f:
        target_inst_ids = json.load(f)["target_inst_ids"]
    return _load_dataset(*args, **kwargs).filter(
        input_columns=["instance_id"],
        function=lambda x: x in target_inst_ids,
    )
