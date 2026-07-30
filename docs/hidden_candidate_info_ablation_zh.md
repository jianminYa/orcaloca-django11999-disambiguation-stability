# Hidden Candidate Info 消融说明

## 目的

这个实验用来回答一个比 `no_disamb` 更严格的问题：

> 如果搜索工具发现实体名有多个候选位置，但完全不把候选文件路径展示给 LLM，只告诉它“存在歧义”，agent 还能否通过其它 search API 间接找到正确位置？

这和原来的 `no_disamb` 不一样：

- `no_disamb`：LLM 仍然能看到 `<Disambiguation>` 候选列表，只是不自动把候选变成队列动作。
- `hidden_candidate_info`：LLM 看不到候选路径，只看到 `<AmbiguousSearch>` 提示；候选列表只写入内部 artifact，供实验分析。

## 代码改动

主要改动在：

```text
source/OrcaLoca/Orcar/search/search_tool.py
```

新增环境变量：

```text
ORCALOCA_HIDE_DISAMBIGUATION_CANDIDATES=1
ORCALOCA_HIDDEN_DISAMBIGUATION_LOG=<path>
```

当隐藏开关关闭时，行为保持原样：

```text
<Disambiguation>
Possible Location 1:
File Path: ...
...
</Disambiguation>
```

当隐藏开关开启时，LLM 只看到：

```text
<AmbiguousSearch>
The class query `Options` matches multiple repository entities.
Candidate locations are hidden in this ablation and were not shown to you.
Please refine the query using search_file_tree, search_file_contents, or retry with an explicit file_path if you can infer a likely path.
</AmbiguousSearch>
```

真实候选被写入：

```text
artifacts/django11999/runs/hidden_candidate_info/<trial>/hidden_disambiguation_candidates.jsonl
```

例如 `trial_01` 记录：

```json
{"query_kind": "class", "query": "Options", "candidate_count": 2, "candidates": [{"type": "class", "file_path": "django/db/models/options.py", "class_name": null}, {"type": "class", "file_path": "django/core/cache/backends/db.py", "class_name": null}]}
```

## 实验配置

配置文件：

```text
configs/search_hidden_candidate_info.cfg
```

关键参数：

```text
class = True
file = True
disambiguation = False
priority scheduling = enabled
top_k_disambiguation = 3
top_k_methods = 3
top_k_functions = 2
```

运行命令：

```bash
RUN_GROUPS=hidden_candidate_info TRIALS=5 ./scripts/run_django11999_stability_experiment.sh
```

## 实验结果

`django__django-11999` 的 gold localization 是：

```text
django/db/models/fields/__init__.py:Field.contribute_to_class
```

5 次 hidden-candidate 结果：

| Trial | File Match | Function Match | Hidden AmbiguousSearch | 最终定位 |
| --- | --- | --- | ---: | --- |
| trial_01 | yes | yes | 1 | 包含 `Field.contribute_to_class` |
| trial_02 | yes | yes | 0 | 包含 `Field.contribute_to_class` |
| trial_03 | yes | yes | 0 | 包含 `Field.contribute_to_class` |
| trial_04 | no | no | 0 | 只包含 `django/db/models/base.py:ModelBase.*` |
| trial_05 | no | no | 0 | 只包含 `django/db/models/base.py:ModelBase.*` |

汇总：

```text
completed: 5/5
file match: 3/5
function match: 3/5
hidden ambiguous messages: 1
selected disambiguation actions: 0
logged tokens: 494,538
```

## 如何解释

这个结果要保守解释。

第一，hidden 组比 `no_disamb` 更严格，因为它不把候选路径给 LLM 看。但在这 5 次里，真正触发隐藏候选提示的只有 `trial_01`，而且查询是 `Options`，不是关键的 `Field` 或 `contribute_to_class`。

第二，`trial_04` 和 `trial_05` 失败的直接原因不是“隐藏了关键候选路径”，而是 agent 的搜索路径一直停留在：

```text
django/db/models/base.py:ModelBase.__new__
django/db/models/base.py:ModelBase._prepare
django/db/models/base.py:ModelBase.add_to_class
```

它没有发出 `search_class("Field")`、`search_callable("contribute_to_class")`，也没有直接搜索：

```text
django/db/models/fields/__init__.py:Field.contribute_to_class
```

因此倒排索引和隐藏候选机制都没有机会介入。

第三，这个单 issue 说明的是机制边界：候选列表、自动队列动作和 priority scheduling 只有在搜索动作命名到歧义实体时才生效。如果初始 search policy 没有把正确实体名纳入搜索空间，消歧模块不能凭空恢复正确位置。

## 对迁移到 RepoMem 的启示

如果把 OrcaLoca 的消歧机制迁移到 repository memory / issue memory 系统，建议不要只做“提示 LLM 存在重名实体”。更稳妥的设计是：

1. RepoMem 或 LLM 先提出实体名、文件名、类名、方法名。
2. 对这些实体名查运行时倒排索引，得到候选路径。
3. 对文件/类级别重名，尽量保留较宽候选集合，并转成结构化待执行 search task。
4. 对函数/方法级别重名，可用 CodeScorer 或 memory score 做 top-k 裁剪。
5. 在关键候选没有被读取前，不应只凭 LLM 一轮判断 early stop。

这样做的核心不是把候选文本塞进 prompt，而是把候选变成可追踪、可执行、可审计的搜索任务。
