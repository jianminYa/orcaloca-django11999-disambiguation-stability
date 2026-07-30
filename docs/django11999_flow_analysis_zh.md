# django__django-11999 消歧稳定性分析

## 问题背景

`django__django-11999` 的 issue 是：

用户在 Django model 中自定义了 `get_foo_bar_display()`，但 Django 2.2+ 中该方法被 choices 字段自动生成的 `get_FOO_display()` 覆盖，导致无法 override。

正确定位是：

```text
django/db/models/fields/__init__.py:Field.contribute_to_class
```

关键代码语义是：`Field.contribute_to_class()` 在 field 有 `choices` 时会给 model class 设置 `get_%s_display`，旧版本行为下这里可能覆盖用户自定义方法。

## 实验变量

本仓库只对比一个变量：

- standard：`class=True`, `file=True`, `disambiguation=True`
- no_disamb：`class=True`, `file=True`, `disambiguation=False`
- hidden_candidate_info：`class=True`, `file=True`, `disambiguation=False`，并隐藏歧义候选路径，只返回 `<AmbiguousSearch>` 简短提示

其它保持一致：

- dataset wrapper: `SWE-bench_common`, split `test`
- instance: `django__django-11999`
- model: `gpt-5.4-mini`
- priority scheduling: enabled
- context control: enabled
- top_k_search: 12
- top_k_output: 3
- top_k_disambiguation: 3
- top_k_methods: 3
- top_k_functions: 2
- max output tokens: 4096

## OrcaLoca 的完整执行流程

### 1. Trace analysis

`evaluation/run.py` 为 issue 准备 Docker 环境，并调用 trace analysis。

trace analysis 会根据 issue 描述生成或修正 reproducer，在容器内运行，然后从 reproducer、trace 和日志中提取 suspicious code。

在本 issue 的一次成功 trace 中，模型提取到：

```text
_get_FIELD_display
django/db/models/base.py:Model._get_FIELD_display
```

这不是最终 bug 点，但它解释了运行时输出为什么变成 choices label，并给 search 阶段提供了入口。

### 2. Search agent 生成搜索动作

SearchAgent 每一轮会接收：

- issue statement
- trace analysis 输出
- 上一轮 `<New Info>`
- 历史 search result/cache

然后输出 JSON：

```json
{
  "observation_feedback": "...",
  "potential_bug_locations": [...],
  "new_search_actions": [...]
}
```

这些 action 会进入 `SearchQueue`。每轮 `batch_size=1`，因此每次只执行队列中的一个 action。

### 3. SearchManager 执行搜索工具

常见 action 包括：

- `search_class`
- `search_method_in_class`
- `search_callable`
- `search_file_contents`
- `search_source_code`

如果 action 已经包含精确 `file_path`，SearchManager 会直接读取该位置。

如果 action 没有精确路径，并且 query 在倒排索引里有多个候选，SearchManager 返回 `<Disambiguation>` 候选列表。

### 4. Decomposition

standard 和 no-dis 都保留 class/file decomposition：

- 读到一个 class skeleton 后，CodeScorer 会给 class 里的方法打分，挑 top methods 加入队列。
- 读到一个 file skeleton 后，CodeScorer 会给 file 里的函数/类打分，挑 top functions 加入队列。

只有 standard 额外保留 disambiguation decomposition：

- 如果搜索结果是 `<Disambiguation>`：
  - class/file 歧义：把所有具体候选路径转换成精确 search action。
  - method/callable 歧义：读取候选代码片段，用 CodeScorer 根据 issue statement 打分，再按 `score_threshold` 和 `top_k_disambiguation` 裁剪。
- 加入队列时使用 decomposition priority，所以会比普通 LLM 推荐动作更早执行。

### 5. 终止与最终输出

SearchAgent 不会在第一次看到正确函数时立即停止。它会继续：

- 让 LLM 判断是否还需要搜索；
- 如果队列为空，进入 conclusion；
- 如果连续观察高度相似并达到窗口阈值，early stop；
- 最后把 `potential_bug_locations` 或 conclusion 解析成 `searcher_*.json`。

因此，一个 trial 即使已经读取了正确代码，也可能最终输出 miss；反过来，一个 trial 即使未触发 disambiguation，也可能靠 class/file decomposition 或 LLM 直接精确搜索找到正确函数。

## 旧 Common93 单次差异是怎么来的

旧 Common93 单次结果中：

- standard: file/function match
- no_disamb: file/function miss

摘录见：

- `artifacts/django11999/previous_common93_reference/old_single_run_summary.json`
- `artifacts/django11999/previous_common93_reference/standard_key_excerpt.txt`
- `artifacts/django11999/previous_common93_reference/no_disamb_key_excerpt.txt`

旧 standard 的关键路径：

1. LLM 发出未限定路径的 `search_class("Field")`。
2. SearchManager 通过倒排索引发现 `Field` 有 3 个候选。
3. standard 的 disambiguation decomposition 自动生成 3 个精确候选 action：
   - `django/contrib/gis/gdal/field.py:Field`
   - `django/db/models/fields/__init__.py:Field`
   - `django/forms/fields.py:Field`
4. 正确候选进入队列后，class decomposition 进一步选择 `Field.contribute_to_class`。
5. 最终输出命中正确函数。

旧 no-dis 的关键路径：

1. LLM 后续发出未限定路径的 `search_callable("contribute_to_class")`。
2. SearchManager 返回 14 个 `contribute_to_class` 候选。
3. 因为 `disambiguation=False`，这些候选没有被自动转换成具体 search action。
4. LLM 虽然看到了候选文本，但没有稳定选择正确 `django/db/models/fields/__init__.py:Field.contribute_to_class`。
5. 最终输出停留在 `django/db/models/base.py:ModelBase.*`。

这说明旧单次差异中，disambiguation decomposition 的确提供了“把重名实体候选落成可执行搜索动作”的机制支持。

## 最终重复实验结果

本次对 `django__django-11999` 做了 5 次 standard、5 次 no-disambiguation 和 5 次 hidden-candidate 重复实验。

| 组别 | 完成 | file match | function match | `<Disambiguation>` 文本次数 | `<AmbiguousSearch>` 隐藏提示 | 自动加入队列的消歧动作 | 日志 token 总量 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| standard | 5/5 | 4/5 | 4/5 | 1 | 0 | 1 | 812,783 |
| no_disamb | 5/5 | 5/5 | 5/5 | 2 | 0 | 0 | 536,736 |
| hidden_candidate_info | 5/5 | 3/5 | 3/5 | 0 | 1 | 0 | 494,538 |

逐轮结果见：

- `artifacts/django11999/trial_summary.csv`
- `artifacts/django11999/trial_summary.json`

结论是：这个 issue 不能作为“消歧机制稳定提升定位准确率”的强单例证据。旧 Common93 单次结果里确实出现过 `standard match / no_disamb miss`，而且从日志看 disambiguation 当时确实提供了有效帮助；但重复 5 次后，no-disambiguation 反而 5/5 都命中，standard 有 1 次 miss。更强的 hidden-candidate 组为 3/5，但其中只有 1 次真正触发了隐藏歧义提示，所以不能把 3/5 直接解释为“候选路径缺失必然导致性能下降”。

## 为什么旧单次差异不是稳定结论

旧单次差异说明的是一种真实机制路径：

1. LLM 发出未限定路径的 `search_class("Field")`。
2. 倒排索引发现 Django 里有 3 个 `Field` 类。
3. standard 把这 3 个候选自动转换成精确 `search_class(..., file_path=...)` 动作。
4. 其中 `django/db/models/fields/__init__.py:Field` 被读取后，class decomposition 进一步找到 `Field.contribute_to_class`。
5. 最终定位命中。

但重复实验显示，`gpt-5.4-mini` 在这个 issue 上经常不需要这条路径。很多 trial 的第一轮 search 就已经把正确函数写进 `new_search_actions`：

```text
search_method_in_class(
  class_name="Field",
  method_name="contribute_to_class",
  file_path="django/db/models/fields/__init__.py"
)
```

这种 action 已经是精确路径，不会触发倒排索引消歧。no-disambiguation 也保留 class decomposition、file decomposition、priority scheduling 和上下文管理，所以它仍然可以通过直接搜索或类分解找到正确函数。

## standard trial_02：消歧确实发挥作用的例子

最清晰的机制例子是 `standard/trial_02`。

关键 artifact：

- `artifacts/django11999/runs/standard/trial_02/logs/orcar_total.log`
- `artifacts/django11999/runs/standard/trial_02/logs/action_history.log`
- `artifacts/django11999/inverted_index/django11999_disambiguation_events.jsonl`
- `artifacts/django11999/inverted_index/django11999_selected_disambiguation_actions.txt`

执行流程：

1. SearchAgent 产生了 `search_class("Field")`。
2. SearchManager 查询运行时倒排索引，发现 `Field` 有 3 个候选：
   - `django/contrib/gis/gdal/field.py`
   - `django/db/models/fields/__init__.py`
   - `django/forms/fields.py`
3. 搜索工具返回 `<Disambiguation>` 文本。
4. standard 中 `config["disambiguation"] = True`，所以 `_disambiguation_ranking()` 被调用。
5. 对 class/file 歧义，OrcaLoca 不做 CodeScorer 裁剪，而是把全部候选变成精确 action。
6. 这些 action 通过 `append_with_priority(... priority_dict["decomposition"])` 进入优先队列。
7. 正确的 `django/db/models/fields/__init__.py:Field` 被读取，后续 class decomposition 对 `Field` 内方法打分并选择 `contribute_to_class`。

这说明消歧的价值不是“多给 LLM 一段提示文本”，而是把候选列表变成强制执行的搜索动作，减少 LLM 看到候选后不跟进的风险。

## no_disamb trial_03 / trial_05：为什么关闭消歧仍能命中

no-disambiguation 组只关闭：

```text
[SCORE_DECOMPOSITION]
disambiguation = False
```

它没有关闭：

- priority scheduling
- class decomposition
- file decomposition
- trace analysis
- search cache/context management
- LLM 自己生成精确路径 action 的能力

因此当工具返回 `<Disambiguation>` 时，候选文本仍然会进入 LLM 观察，但不会被 `_disambiguation_ranking()` 自动转换成队列动作。换句话说：

- standard：候选文本 + 自动候选 action。
- no_disamb：只有候选文本，后续是否搜索具体候选交给 LLM 自己判断。

在本 issue 中，no-disambiguation 的多个 trial 仍能靠 LLM 直接给出正确路径或靠 class decomposition 找到 `Field.contribute_to_class`，因此结果并没有下降。

## hidden_candidate_info：完全不展示候选路径的更强消融

为了回应“如果完全不给 agent 候选路径，只告诉它存在重名实体，它还能不能找到正确位置”的问题，本仓库额外加入了 `hidden_candidate_info` 组。

实现方式：

1. 搜索配置仍关闭 `disambiguation=False`，因此不会把候选自动变成队列动作。
2. 当 `SearchManager` 原本要返回 `<Disambiguation>` 候选列表时，改为返回：

```text
<AmbiguousSearch>
The <query_kind> query `<query>` matches multiple repository entities.
Candidate locations are hidden in this ablation and were not shown to you.
Please refine the query using search_file_tree, search_file_contents, or retry with an explicit file_path if you can infer a likely path.
</AmbiguousSearch>
```

3. 真正的候选路径不会进入 LLM observation，而是写入：

```text
artifacts/django11999/runs/hidden_candidate_info/<trial>/hidden_disambiguation_candidates.jsonl
```

这组的结果是：

| Trial | File Match | Function Match | 是否触发隐藏歧义提示 | 最终定位 |
| --- | --- | --- | ---: | --- |
| trial_01 | yes | yes | 1 | 包含 `Field.contribute_to_class` |
| trial_02 | yes | yes | 0 | 包含 `Field.contribute_to_class` |
| trial_03 | yes | yes | 0 | 包含 `Field.contribute_to_class` |
| trial_04 | no | no | 0 | 只停留在 `django/db/models/base.py:ModelBase.*` |
| trial_05 | no | no | 0 | 只停留在 `django/db/models/base.py:ModelBase.*` |

需要注意：唯一一次 hidden 提示是 `trial_01` 的 `Options` 类歧义：

```json
{"query_kind": "class", "query": "Options", "candidate_count": 2}
```

它不是本 issue 的 gold 位置。因此 hidden 组不能证明“隐藏 `Field` / `contribute_to_class` 候选后模型失败”，因为这 5 次里模型并没有对关键实体触发隐藏候选。它能说明的是：如果没有候选路径自动执行保障，agent 更依赖自身 search path；当 search path 没有扩展到 `django/db/models/fields/__init__.py` 时，最终就容易 miss。

## standard trial_05：为什么 standard 也会 miss

`standard/trial_05` 的最终输出是：

```text
django/db/models/base.py:ModelBase.__new__
django/db/models/base.py:Model._get_FIELD_display
```

它没有输出 gold function：

```text
django/db/models/fields/__init__.py:Field.contribute_to_class
```

从日志看，原因不是 disambiguation 后处理失败，而是这一轮搜索路径一直围绕 `django/db/models/base.py`。LLM 没有发出未限定的 `search_class("Field")` 或 `search_callable("contribute_to_class")`，也没有发出精确的 `Field.contribute_to_class` action。因此倒排索引消歧没有机会介入。

这点很重要：消歧模块只能处理“已经被搜索动作命名出来的歧义实体”。如果初始 search policy 没有把正确实体名字纳入 action 空间，disambiguation 无法凭空恢复。

## 对迁移设计的启示

如果把 OrcaLoca 的 disambiguation 思路迁移到其他 agent 或 repository memory 系统，建议不要只把候选列表塞进 prompt。更稳的设计是：

1. 对 issue / memory 检索出的实体名查倒排索引。
2. 如果命中多个文件/类/方法候选，把候选保存为结构化待执行任务。
3. 对 class/file 级歧义，优先保留所有候选或至少保留更宽的候选集合，不要过早只取 top1。
4. 对 method/function 级歧义，可以用 code scorer 或 repo memory score 选 top-k。
5. 在所有关键歧义候选被执行前，不应仅因为 LLM 当前判断“足够了”就 early stop。

本 issue 的重复实验说明，消歧机制本身是候选执行保障机制；但单个 issue 的最终分数还会受到 trace analysis、初始 search action、class/file decomposition、LLM 随机路径和 early stop 共同影响。
