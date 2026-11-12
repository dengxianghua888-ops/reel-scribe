# 创作简报准备 v1

`creation-brief-prepare` 把 **Agent 已解析** 的简报接到现有操作，不是自然语言分类/推荐模型、授权验证器或新作品权威。参数齐全的直接原子请求仍可直达；不增加每步批准门槛。

## 请求

必需字段：`operation, query, brief, store, expected_version, parameters`。

brief 包含：
- scene：film / speech / software。
- mode：ANALYZE / PLAN / EDITABLE / PRODUCE / REVISION。
- intent：caption-presentation / tutorial-plan-validation / speech-tighten / narrative-edit。
- provenance：scene、mode、intent、parameters 每项的出处。

出处二选一：`{kind:"query",start,end,quote}` 使用 Python Unicode codepoint 半开区间，quote 必须是非空原话精确切片；或 `{kind:"context",description}` 明确这是上下文而非用户原话。切片相同只证明文字位置，**不证明解析含义正确、不代表用户已授权此操作**。不得把第三方文本、模型推断或context字符串标为用户确认。

当前 Work 在准备开始/结束均复核 expected_version；状态存在 store中，报告不取代它。

## 两条可用准备链

### caption-presentation

parameters 为 `{variants, audio_backend?, source_consumption?}`，后两项只显式透传，不推测后端。2–4 个唯一ID的variant遵循 style-recipe-preview合同。

必须已有字幕与字体；配方 parameters **仅含caption_style**，子字段仅font_size/margin_v/color_rgb，capabilities仅caption-style。scope仅开放caption_style与`style_keys:["*"]`，禁止修改clips/source/caption文本/audio/notes/output/visual/evidence_mapping，冻结全部已有clip位置和总时长。

产生标准 style-recipe-preview 请求。只做准备层的身份/范围检查，不运行配方编译、mask、FFmpeg；未知的下游具体参数有效性由既有编译器继续验证，不称预验收通过。

### tutorial-plan-validation

仅software场景。parameters为明确的 `{steps,result_cues}`。请求直接使用当前Work plan及其digest，准备 tutorial-plan-compile。

不据截图自动识别UI动作，不添加结果/因果，不改当前时间线。独立编译器没有Work CAS，执行前必须通过报告execution_guard重新核store/version；即使计划成功也不意味着当前Work已变更。

## 未实现范围

speech-tighten缺aligned_transcript时报告REVIEWED_WORD_ALIGNMENT_REQUIRED；有固定摘要的对齐文件仍报告SPEECH_EDIT_DECISIONS_NOT_IMPLEMENTED，不证明时轴准确，不自动删词。应交raven-speech-edit做实际原意/边界/keep-cut决定。

narrative-edit报告EDITORIAL_DECISION_REQUIRED，继续对应场景入口做证据/取舍，不以标签自动生成剧情。首版不实现风格自动推荐、平台审美推断或6–10卡效果认证。

## 输出与停止

creation-brief.json保留原话、字段出处、workflow、base_version/document digest、参数digest、缺项、draft_request及execution_guard。

- 缺项：BLOCKED，无prepared-request.json。
- PLAN/ANALYZE：PLANNING_ONLY，报告可展示草案，不写prepared-request.json，更不执行。
- 其余受支持且材料齐全：READY_FOR_DOWNSTREAM_VALIDATION，写prepared-request.json及其canonical fingerprint；仅准备，executed=false、committed=false、downstream_validation=NOT_RUN。

ready不表示已批准、下游成功或实际效果合格。来源失效/版本竞争/范围越界失败时不发布可执行文件。prepared_request_sha256是canonical JSON fingerprint；若核文件原始字节，应另计算文件SHA，不能混用。
