# OrcaLoca django__django-11999 消歧稳定性实验

本仓库记录了一个针对 `django__django-11999` 的 OrcaLoca 定位实验，主要回答两个问题：

1. 之前在 Common93 消融实验中观察到的 `standard match / no_disamb miss`，是否说明 OrcaLoca 的 disambiguation decomposition 对这个 issue 有稳定提升？
2. OrcaLoca 的倒排索引是在运行时构建，还是离线预先构建？它在这个 issue 中具体包含什么内容、如何被使用？

简要结论：

- 对 `django__django-11999` 单个 issue 重复实验后，结果不支持“消歧机制在该样例上稳定提升”的强结论。
- 5 次 standard 实验中，4 次 file/function match；5 次关闭 disambiguation 的实验中，5 次 file/function match。
- 这说明之前那次 `standard match / no_disamb miss` 更可能是 LLM 搜索路径波动造成的单次现象。
- 但消歧机制本身确实存在明确作用：当模型搜索到歧义实体名，例如 `Field`，OrcaLoca 可以通过运行时倒排索引把这个名字展开为多个具体文件路径上的搜索动作，从而提高正确候选进入后续上下文的概率。

## 实验设置

实验对象：

```text
django__django-11999
```

数据集封装：

```text
SWE-bench_common / test split
```

评分使用的 gold localization：

```text
django/db/models/fields/__init__.py:Field.contribute_to_class
```

模型与后端：

- 定位阶段模型：`gpt-5.4-mini`
- API 后端：OpenAI-compatible endpoint
- API key 和 base url 均从环境变量或 `key.cfg` 读取
- 仓库中不提交 key、真实 endpoint、conda 环境、Docker 镜像或运行时 cache

对比组：

| 组别 | 配置 | 说明 |
| --- | --- | --- |
| standard | `class=True`, `file=True`, `disambiguation=True` | OrcaLoca 标准定位流程 |
| no_disamb | `class=True`, `file=True`, `disambiguation=False` | 只关闭 disambiguation decomposition，其余保持一致 |

保持不变的参数：

| 参数 | 值 |
| --- | --- |
| priority scheduling | enabled |
| class decomposition | enabled |
| file decomposition | enabled |
| `top_k_disambiguation` | 3 |
| `top_k_methods` | 3 |
| `top_k_functions` | 2 |
| `ORCALOCA_MAX_TOKENS` | 4096 |
| 每组重复次数 | 5 |

## 实验结果

汇总命令：

```bash
python scripts/summarize_django11999_trials.py --root .
```

总体结果：

| 组别 | 完成数 | File Match | Function Match | Disambiguation 日志消息 | 实际选中的消歧动作 | 日志记录 token |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| standard | 5/5 | 4/5 | 4/5 | 1 | 1 | 812,783 |
| no_disamb | 5/5 | 5/5 | 5/5 | 2 | 0 | 536,736 |

逐次结果：

| 组别 | Trial | File Match | Function Match | Disambiguation Message | Selected Disambiguation Action | 最终定位函数 |
| --- | --- | --- | --- | ---: | ---: | --- |
| standard | trial_01 | yes | yes | 0 | 0 | `Field`, `Field.contribute_to_class` |
| standard | trial_02 | yes | yes | 1 | 1 | `ModelBase`, `ModelBase.add_to_class`, `Field`, `Field.contribute_to_class` |
| standard | trial_03 | yes | yes | 0 | 0 | `ModelBase`, `ModelBase.__new__`, `ModelBase.add_to_class`, `Field`, `Field.contribute_to_class` |
| standard | trial_04 | yes | yes | 0 | 0 | `Model`, `Model._get_FIELD_display`, `Field`, `Field.contribute_to_class` |
| standard | trial_05 | no | no | 0 | 0 | `ModelBase`, `ModelBase.__new__`, `Model`, `Model._get_FIELD_display` |
| no_disamb | trial_01 | yes | yes | 0 | 0 | `ModelBase`, `ModelBase.__new__`, `ModelBase._prepare`, `Field`, `Field.contribute_to_class` |
| no_disamb | trial_02 | yes | yes | 0 | 0 | `Model`, `Model._get_FIELD_display`, `Field`, `Field.contribute_to_class` |
| no_disamb | trial_03 | yes | yes | 1 | 0 | `Model`, `Model._get_FIELD_display`, `Field`, `Field.contribute_to_class` |
| no_disamb | trial_04 | yes | yes | 0 | 0 | `Model`, `Model._get_FIELD_display`, `Field`, `Field.contribute_to_class` |
| no_disamb | trial_05 | yes | yes | 1 | 0 | `ModelBase`, `ModelBase.__new__`, `ModelBase.add_to_class`, `Field`, `Field.contribute_to_class` |

## 结果解释

这个 issue 的 repeated experiment 表明：

1. `django__django-11999` 不是一个可以稳定证明 disambiguation decomposition 提升的样例。
2. 关闭 disambiguation 后，模型仍然经常可以直接提出正确路径 `django/db/models/fields/__init__.py`，或通过 class/file decomposition 找到 `Field.contribute_to_class`。
3. standard 组的 `trial_02` 是一个清楚的机制例子：模型搜索 `Field` 后，OrcaLoca 识别到该实体名有多个候选位置，于是把多个具体 `search_class(Field, file_path=...)` 动作加入后续搜索流程，正确文件因此进入上下文。
4. standard 组的 `trial_05` 没有定位成功，是因为模型搜索路径停留在 `django/db/models/base.py` 附近，没有搜索 `Field` 或 `contribute_to_class`。如果没有产生包含正确实体名的歧义查询，disambiguation 模块就没有机会发挥作用。
5. no_disamb 组中有两次日志出现了 `<Disambiguation>` 文本，但由于配置关闭了 disambiguation decomposition，没有实际生成消歧搜索动作，最终 match 主要来自 LLM 直接路径判断和其他 decomposition 流程。

因此，适合对师兄汇报的表述是：

> 针对 `django__django-11999` 的重复实验显示，单个样例上 standard 与 no_disamb 的差异不稳定。消歧机制确实能把歧义实体名展开为具体搜索动作，但该 issue 中模型本身经常能直接找到正确文件和函数，所以不能把之前单次 no_disamb miss 解释为稳定消歧收益。

## 倒排索引是什么时候创建的

OrcaLoca 的倒排索引不是离线下载的数据文件，也不是预先随仓库提交的静态索引。它是在每个 issue 运行时，根据当前 checkout 出来的目标仓库源码动态构建。

核心调用链：

```text
Orcar.agent.Orcar.run_search_agent()
  -> SearchAgent(...)
  -> SearchManager(repo_path=...)
  -> SearchManager._setup_graph()
  -> RepoGraph(repo_path=...)
  -> RepoGraph.build_whole_graph(repo_path)
  -> InvertedIndex()
```

构建逻辑：

1. SWE-bench/OrcaLoca 先 checkout 当前 issue 对应的项目仓库。
2. `RepoGraph` 解析仓库源码，抽取文件、类、函数、方法、全局变量等实体。
3. `InvertedIndex` 以实体名为 key，保存多个候选位置。
4. `remove_single_value_key()` 会删除只有一个候选位置的 key，只保留重名或多候选实体。
5. 搜索时，如果模型查询的实体名命中了倒排索引中的多候选 key，OrcaLoca 就可以触发 disambiguation decomposition，把一个模糊实体名拆成多个具体 `file_path` 上的搜索动作。

本次已导出该 issue 对应 Django checkout 的运行时 duplicate-key index：

| 文件 | 说明 |
| --- | --- |
| `artifacts/django11999/inverted_index/django_duplicate_inverted_index.jsonl` | 完整 duplicate-key 倒排索引导出 |
| `artifacts/django11999/inverted_index/django_duplicate_index_stats.json` | 索引统计信息 |
| `artifacts/django11999/inverted_index/django11999_focused_queries.json` | 与本 issue 相关的关键查询，例如 `Field`、`contribute_to_class` |
| `artifacts/django11999/inverted_index/django11999_disambiguation_events.jsonl` | 实验日志中抽取出的消歧事件 |
| `artifacts/django11999/inverted_index/django11999_selected_disambiguation_actions.txt` | 实际被选择执行的消歧动作 |

关键统计：

| 指标 | 值 |
| --- | ---: |
| duplicate key count | 1168 |
| duplicate candidate total | 7014 |
| max candidate count | 665 |
| `Field` candidate classes | 3 |
| `contribute_to_class` candidate methods | 14 |

`Field` 在运行时倒排索引中有 3 个候选 class：

```text
django/contrib/gis/gdal/field.py
django/db/models/fields/__init__.py
django/forms/fields.py
```

其中正确位置是：

```text
django/db/models/fields/__init__.py
```

`contribute_to_class` 在倒排索引中有 14 个 method 候选，其中包含正确的：

```text
django/db/models/fields/__init__.py:Field.contribute_to_class
```

## 如何复现实验

准备环境变量：

```bash
export OPENAI_API_KEY=...
export OPENAI_BASE_URL=...
```

运行 5 次 standard + 5 次 no_disamb：

```bash
TRIALS=5 ./scripts/run_django11999_stability_experiment.sh
```

如果当前 shell 没有激活 OrcaLoca 环境，可以显式指定 Python：

```bash
PYTHON_BIN=/path/to/python TRIALS=5 ./scripts/run_django11999_stability_experiment.sh
```

重新汇总结果：

```bash
python scripts/summarize_django11999_trials.py --root .
```

重新导出倒排索引：

```bash
python scripts/export_runtime_index.py --root .
```

## 文件结构怎么看

关键文件：

| 路径 | 内容 |
| --- | --- |
| `README.md` | 英文总览 |
| `README_zh.md` | 中文总览 |
| `docs/django11999_flow_analysis_zh.md` | 针对 `django__django-11999` 的详细中文流程分析 |
| `docs/runtime_inverted_index_zh.md` | 运行时倒排索引机制说明 |
| `docs/artifacts_guide_zh.md` | 中间文件阅读指南 |
| `artifacts/django11999/trial_summary.csv` | 10 次实验逐行汇总 |
| `artifacts/django11999/trial_summary.json` | 机器可读的汇总结果 |
| `artifacts/django11999/runs/<group>/<trial>/searcher_django__django-11999.json` | 每次 OrcaLoca 最终定位输出 |
| `artifacts/django11999/runs/<group>/<trial>/logs/orcar_total.log` | 每次运行的主日志 |
| `artifacts/django11999/runs/<group>/<trial>/logs/action_history.log` | 搜索动作历史日志 |
| `artifacts/django11999/inverted_index/` | 本次导出的运行时倒排索引与相关分析 |
| `scripts/` | 实验运行、汇总、导出、脱敏脚本 |
| `source/OrcaLoca/` | 本次实验使用的 OrcaLoca 源码快照 |

注意：

- `work/` 目录是运行时 worktree/cache，不提交到 GitHub。
- `key.cfg`、API key、真实 API endpoint 不提交。
- Docker 镜像、conda 环境、Hugging Face cache 不提交。

## 给师兄的简短回答

如果被问“实验设置是什么，用的 LLM 是什么，中间结果有没有保留”，可以这样回答：

> 这次针对 `django__django-11999` 单独做了 5 次 standard 和 5 次关闭 disambiguation 的重复实验，其他参数保持一致，只把 `disambiguation=True/False` 作为变量。定位阶段使用 `gpt-5.4-mini`，通过 OpenAI-compatible API 调用。中间结果已经保留，包括每次 OrcaLoca 的最终 localization JSON、主日志、action history、消歧事件、运行时倒排索引导出和汇总表，都放在 GitHub 仓库的 `artifacts/django11999/` 下。

如果被问“倒排索引在哪里”，可以回答：

> OrcaLoca 的倒排索引不是离线文件，而是在每个 issue 运行时根据 checkout 出来的目标仓库源码动态构建。我们这次把 `django__django-11999` 对应 Django 仓库构建出的 duplicate-key index 导出了，放在 `artifacts/django11999/inverted_index/`，里面可以看到 `Field` 有 3 个候选 class，`contribute_to_class` 有 14 个候选 method。

如果被问“这个例子是否证明消歧稳定有效”，可以回答：

> 这个单例重复实验不能证明稳定提升。standard 是 4/5 match，no_disamb 是 5/5 match。但日志说明消歧机制确实能在模型搜索到歧义实体时，把模糊名字展开成具体文件路径上的搜索动作。它更适合作为机制证据，而不是这个单个 issue 上的稳定收益证据。
