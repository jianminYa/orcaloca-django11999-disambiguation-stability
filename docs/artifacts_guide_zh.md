# Artifact 阅读指南

本仓库只提交复现实验需要的源码、脚本和精简 artifacts。完整临时工作目录 `work/` 不提交，因为它包含每轮 checkout、cache 和 Docker/环境中间状态。

最终实验结果：

- standard：5/5 完成，4/5 file match，4/5 function match。
- no_disamb：5/5 完成，5/5 file match，5/5 function match。
- 结论：`django__django-11999` 上旧单次 `standard match / no_disamb miss` 不是稳定复现结果。

## 目录结构

```text
.
├── README.md
├── configs/
│   ├── search_standard.cfg
│   └── search_no_disamb.cfg
├── scripts/
│   ├── run_django11999_stability_experiment.sh
│   ├── summarize_django11999_trials.py
│   ├── collect_trial_artifacts.py
│   ├── sanitize_artifacts.py
│   ├── export_runtime_index.py
│   └── extract_previous_common93_reference.py
├── source/OrcaLoca/
└── artifacts/django11999/
    ├── experiment_metadata.json
    ├── swe_bench_common93_test.jsonl
    ├── trial_summary.csv
    ├── trial_summary.json
    ├── inverted_index/
    ├── previous_common93_reference/
    └── runs/
```

## 关键文件怎么看

`artifacts/django11999/trial_summary.csv`

每行是一组一次重复实验：

- `group`: `standard` 或 `no_disamb`
- `trial`: 重复编号
- `completed`: 是否生成最终 `searcher_*.json`
- `file_match`: 输出文件是否命中 gold file
- `function_match`: 输出函数是否命中 gold function
- `disambiguation_message_count`: 本轮日志中是否出现 `<Disambiguation>`
- `selected_disambiguation_action_count`: standard 是否把候选转换成队列动作
- `model_files`, `model_functions`: 最终模型输出的位置集合

`artifacts/django11999/trial_summary.json`

CSV 的完整 JSON 版本，额外包含每轮 token 计数、API 错误计数、关键日志路径。

其中 `log_paths` 字段保留的是实验运行时的 `work/...` 相对路径，便于本机溯源。GitHub 仓库里阅读日志时，应看已经复制出的：

```text
artifacts/django11999/runs/<group>/<trial>/logs/
```

`artifacts/django11999/runs/<group>/<trial>/searcher_django__django-11999.json`

OrcaLoca search 阶段最终输出，也就是 localization 结果。

`artifacts/django11999/runs/<group>/<trial>/logs/action_history.log`

搜索动作队列和 action 计数日志。看 disambiguation 是否真的起作用，优先看这里是否有：

```text
Disambiguation: [SearchActionStep(...)]
```

如果只有 `<Disambiguation>` 文本但没有这行，说明工具发现了歧义候选，但没有被 decomposition 机制自动加入搜索队列。

`artifacts/django11999/runs/<group>/<trial>/logs/orcar_total.log`

完整 OrcaLoca 合并日志。它记录了：

- trace analysis 输出
- 每轮 LLM 的 JSON action
- 搜索工具返回的 `<New Info>`
- CodeScorer token 计数
- final conclusion

注意：OrcaLoca 在单个 trial 内部重启时可能生成 `log_1/`、`log_2/`。本仓库的 `collect_trial_artifacts.py` 会选择最新有效的 `log*` 目录，并统一复制到 `artifacts/django11999/runs/<group>/<trial>/logs/`。因此阅读 artifacts 时不需要手动关心原始 `log` 还是 `log_1`。

`artifacts/django11999/inverted_index/`

运行时倒排索引导出：

- `django_duplicate_inverted_index.jsonl`: 完整重复键索引，一行一个 key
- `django_duplicate_index_stats.json`: 统计信息
- `django11999_focused_queries.json`: 与该 issue 相关的重点 key
- `django11999_disambiguation_events.jsonl`: 从日志中提取的 disambiguation 事件
- `django11999_selected_disambiguation_actions.txt`: 被自动加入队列的消歧动作

重点看：

- `django11999_focused_queries.json` 中的 `Field`：3 个 class 候选。
- `django11999_focused_queries.json` 中的 `contribute_to_class`：14 个 method 候选。
- `django11999_selected_disambiguation_actions.txt`：standard trial_02 把 3 个 `Field` 候选转换成了精确 `search_class(..., file_path=...)` 动作。

`artifacts/django11999/previous_common93_reference/`

之前 Common93 单次消融中 `django__django-11999` 出现 `standard match / no_disamb miss` 的紧凑摘录。它用于解释为什么最初怀疑 disambiguation 对该 issue 有帮助。
