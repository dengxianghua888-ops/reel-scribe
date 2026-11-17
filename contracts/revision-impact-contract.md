# Revision impact / 1

只读的变更影响规划。复用 `work_ops.revision_diff` 的完整文档、素材哈希、冻结范围、证据保护和时间映射校验，不创建第二份 Work 状态，不提交、渲染、调用服务或复用缓存。

`revision_impact.analyze(base, candidate, scope, tools, expected_base_sha256=..., expected_candidate_sha256=...)` 返回报告。两份摘要必须分别匹配整份文档；`scope` 沿用 `timeline-revise` 合同。两边的源文件都必须仍可读取且哈希匹配。旧源已被同路径覆盖时拒绝，而不是把旧版本认作有效。

操作请求 `operation: revision-impact-inspect`，字段：`document`、`candidate`、`scope`、`expected_document_sha256`、`expected_candidate_sha256`。输出 `revision-impact.json`，绑定两个文档摘要、范围摘要以及不含自身字段的报告摘要 `impact_sha256`。

## 分类与执行依赖

- 字幕颜色、字号、边距：字幕排版、视觉合成、渲染；不要求重新识别、选择镜头或生成配音。
- 字幕文字：同上，但这是显示文字，不证明原声台词被改写，也不冒充重新配音。
- 既有音源的音轨参数或映射：混音、渲染。
- 既有视觉源的视觉层参数：视觉合成、渲染。
- 音轨/视觉层新增、删除、替换源引用（含路径或哈希变化）或改变消费源窗：保守重算全部阶段，不把新配音内容或新画面误标成分析输入未变。
- 镜头内容、排序、时长、速度、输出规格：保守重算内容计划至渲染；可影响后续字幕、音轨及邻接段。
- 源身份变化：全部阶段，包含同一路径的不同哈希；先通过真实源身份检查。
- 证据映射：内容计划。风格绑定和普通备注只是元数据，不自动成为实际效果。

`required_stages` 是需要重新考虑/执行的阶段；`unchanged_dependency_stages` 仅表示此文档比较未发现该类依赖变化。不是“缓存可用”或“验证通过”。无部分渲染边界证据，整件作品保守处理，不将受影响片段 ID 当精确重渲染范围。

## QA 与缓存边界

`invalidated_reviews` 原样保留现行 Work gate 所有失效项；有任何文档变更时，`prior_whole_document_qa: STALE` 明确旧整份文档绑定的 QA 不能继承。即使只有字幕颜色变化，旧 gate 的听检等宽泛失效仍保留。不会用更窄的执行依赖分析降低验收标准。

始终 `cache_reuse: NOT_AUTHORIZED`、`qa_status: NOT_RUN`、`applied_to_work: false`。接入缓存前仍需验证产物字节、完整依赖、模型/提示/后端/参数版本；报告本身不提供这些证明。报告不包含真实素材效果、内容正确性、听检或编辑器验收。相同输入报告可重现；旧摘要、范围越权或未知字段拒绝，不产生报告。
