# OrcaLoca 倒排索引机制说明

## 结论

OrcaLoca 的倒排索引不是随数据集离线下载的文件，也不是预先提交在仓库里的静态产物。它是在每个 issue 的目标仓库 checkout 完成后，由 `SearchManager` 在运行时扫描当前代码仓库并构建的内存结构。

本实验额外导出了 Django checkout 上运行时构建出的重复键索引：

- `artifacts/django11999/inverted_index/django_duplicate_inverted_index.jsonl`
- `artifacts/django11999/inverted_index/django_duplicate_index_stats.json`
- `artifacts/django11999/inverted_index/django11999_focused_queries.json`

## 什么时候创建

创建链路如下：

1. `Orcar.agent.Orcar.run_search_agent()` 创建 `SearchAgent`。
2. `Orcar.search_agent.SearchAgent.__init__()` 创建 `SearchManager(repo_path=...)`。
3. `Orcar.search.search_tool.SearchManager.__init__()` 调用 `_setup_graph()`。
4. `_setup_graph()` 创建 `RepoGraph(repo_path=self.repo_path)`。
5. `Orcar.search.build_graph.RepoGraph.__init__()` 创建 `InvertedIndex()`，解析整个 checkout 仓库，然后调用 `remove_single_value_key()`。

对应源码：

- `source/OrcaLoca/Orcar/agent.py`
- `source/OrcaLoca/Orcar/search_agent.py`
- `source/OrcaLoca/Orcar/search/search_tool.py`
- `source/OrcaLoca/Orcar/search/build_graph.py`
- `source/OrcaLoca/Orcar/search/inverted_index.py`

本仓库的诊断脚本 `scripts/export_runtime_index.py` 也是按照这条路径重新构造：

```python
graph = RepoGraph(repo_path=str(args.repo_path))
index = graph.inverted_index.index
```

因此导出的 jsonl 是“对同一个 checkout 重新运行 OrcaLoca 构图逻辑得到的结果”，不是额外人工整理的候选表。

## 索引里保存什么

`InvertedIndex` 是 `defaultdict(list)`：

- key：文件名、类名、函数名、方法名、全局变量名等实体名称。
- value：`IndexValue(type, file_path, class_name)`。

构建完成后，OrcaLoca 会删除只有一个候选的 key，只保留有多个候选位置的歧义 key。这一点非常重要：运行时索引主要用于判断“一个名字是否歧义”，而不是替代普通代码图搜索。

本实验导出的 Django 索引统计：

- duplicate key 数：1168
- duplicate candidate 总数：7014
- 最大候选数：665
- 候选类型分布：
  - class: 314
  - file: 586
  - function: 240
  - global_variable: 1064
  - method: 4810

## 如何使用

搜索工具在执行未限定路径的搜索时会先查这个索引：

- `search_file_contents(file_name)`：如果文件名有多个匹配，返回 `<Disambiguation>` 候选路径。
- `search_class(class_name)`：如果类名有多个匹配，返回 `<Disambiguation>` 候选路径。
- `search_callable(query_name)`：如果函数/方法名有多个匹配，返回 `<Disambiguation>` 候选路径和 class。
- `search_method_in_class(class_name, method_name)`：如果同名 class/method 组合在多个文件中出现，返回 `<Disambiguation>`。

如果查询没有出现在重复键索引里，说明它在当前仓库中唯一，工具会直接走知识图搜索并返回源码片段或 skeleton。

## django__django-11999 中的关键歧义

这个 issue 的正确定位是：

`django/db/models/fields/__init__.py:Field.contribute_to_class`

运行时索引显示：

- `Field` 是歧义类名，有 3 个候选：
  - `django/contrib/gis/gdal/field.py`
  - `django/db/models/fields/__init__.py`
  - `django/forms/fields.py`
- `contribute_to_class` 是歧义方法名，有 14 个候选，其中正确候选是：
  - `django/db/models/fields/__init__.py`, class `Field`

这说明倒排索引本身可以发现这个 issue 中确实存在重名实体歧义。但完整 OrcaLoca agent 是否触发 disambiguation，还取决于 LLM 在搜索过程中是否发出未限定路径的 action，例如 `search_class("Field")` 或 `search_callable("contribute_to_class")`。

如果 LLM 直接发出精确 action，例如：

```text
search_method_in_class(
  class_name="Field",
  method_name="contribute_to_class",
  file_path="django/db/models/fields/__init__.py"
)
```

那么搜索工具会直接读取该函数，不再经过倒排索引消歧。

## 本次稳定性实验中的作用边界

重复实验显示，倒排索引确实识别出 `Field` 和 `contribute_to_class` 的歧义：

- `Field`：3 个候选 class。
- `contribute_to_class`：14 个候选 method。

但是倒排索引只在搜索动作命名了对应实体时介入。例如：

- 会触发：`search_class("Field")`
- 会触发：`search_callable("contribute_to_class")`
- 不触发：LLM 只搜索 `ModelBase.__new__` 和 `Model._get_FIELD_display`
- 不触发：LLM 已经给出精确 `file_path`，工具可以直接读取

因此 `standard trial_05` 即使开启 disambiguation，也没有命中正确函数：那一轮 search path 没有把 `Field` 或 `contribute_to_class` 作为待消歧实体放进搜索动作。
