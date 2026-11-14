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

## 可用准备链

### caption-presentation

parameters 为 `{variants, audio_backend?, source_consumption?}`，后两项只显式透传，不推测后端。2–4 个唯一ID的variant遵循 style-recipe-preview合同。

必须已有字幕与字体；配方 parameters **仅含caption_style**，子字段仅font_size/margin_v/color_rgb，capabilities仅caption-style。scope仅开放caption_style与`style_keys:["*"]`，禁止修改clips/source/caption文本/audio/notes/output/visual/evidence_mapping，冻结全部已有clip位置和总时长。

产生标准 style-recipe-preview 请求。只做准备层的身份/范围检查，不运行配方编译、mask、FFmpeg；未知的下游具体参数有效性由既有编译器继续验证，不称预验收通过。

### tutorial-plan-validation

仅software场景。parameters为明确的 `{steps,result_cues}`。请求直接使用当前Work plan及其digest，准备 tutorial-plan-compile。

不据截图自动识别UI动作，不添加结果/因果，不改当前时间线。独立编译器没有Work CAS，执行前必须通过报告execution_guard重新核store/version；即使计划成功也不意味着当前Work已变更。

## 未实现范围

speech-tighten缺aligned_transcript时报告REVIEWED_WORD_ALIGNMENT_REQUIRED；缺显式决定字段时报告SPEECH_EXPLICIT_DECISIONS_REQUIRED，不补默认选择。完整桥接见下节。

narrative-edit报告EDITORIAL_DECISION_REQUIRED，继续对应场景入口做证据/取舍，不以标签自动生成剧情。首版不实现风格自动推荐、平台审美推断或6–10卡效果认证。

## 输出与停止

creation-brief.json保留原话、字段出处、workflow、base_version/document digest、参数digest、缺项、draft_request及execution_guard。

- 缺项：BLOCKED，无prepared-request.json。
- PLAN/ANALYZE：PLANNING_ONLY，报告可展示草案，不写prepared-request.json，更不执行。
- 其余受支持且材料齐全：READY_FOR_DOWNSTREAM_VALIDATION，写prepared-request.json及其canonical fingerprint；仅准备，executed=false、committed=false、downstream_validation=NOT_RUN。

ready不表示已批准、下游成功或实际效果合格。来源失效/版本竞争/范围越界失败时不发布可执行文件。prepared_request_sha256是canonical JSON fingerprint；若核文件原始字节，应另计算文件SHA，不能混用。


## speech-tighten：明确词段决定桥接

仅 speech 场景；parameters 必须给齐 aligned_transcript（path+SHA）、expected_transcript_revision、segments、protected_word_ids、allow_reorder=false、source_clip_ids。

- aligned_transcript 是 word-transcript/1 JSON；解析同一次读取的字节与所给SHA对应，拒重复JSON键/非有限数。源检查与有限读取均限制4MiB。expected_transcript_revision 是完整稿canonical fingerprint，不是文件原始SHA。
- timing只接受model-aligned/human-checked上游声明；estimated/未知明确拒绝。**接受声明不认证真实词边界**；不由helper生成金标、听审结论或纠正原文。
- source_clip_ids须是当前Work中按原顺序连续的一组clip，1×、未静音、非静音增益，全部指向同一source_id。转写源path+SHA必须匹配该实际选中源。片段源区间必须连续，不能跨当前Work已删的源间隙；按当前fps逐clip量化后的有效源尾判断可消费范围，段落不得重新引入作品外内容。
- segments沿用现有compiler格式：id、连续word_ids、明确start/end/gain_db、boundary_evidence。边界文件身份校验与末尾重验不等于其结论已审核。helper只核来源/授权源窗/必要字段，不复制编译器的词语连续性、截尾、未列词混入或保护词删除算法。
- 准备 speech-plan-compile 请求，output继承当前Work的fps/width/height/fit。真正词决定合法性仍由该compiler校验；准备成功不能冒充词精剪通过。

speech_binding额外记录稿文件身份、源、允许源窗、上游timing、当前持久保护摘要、dependent_resources、adoption_state=REQUIRES_TIMELINE_REVISE_AND_DEPENDENT_MAPPING、apply_authorized_by_preparation=false、dependent_mapping_validation=NOT_RUN。

已有字幕、音轨、视觉层和持久保护不阻碍**独立计划准备**，也不被删除或修改；它们不是被独立计划自动继承。后续采用必须将已审核计划按显式scope合入最新Work，经timeline-revise核所有依赖/保护及CAS，不能直接替换Work.plan，更不能通过删掉保护来使采用成功。

FLEURS等只有原文/整段录音和比例估时的素材可用于拒绝estimated负例，不能标为真实逐词剪辑正例。音频WAV本身也不满足当前执行计划的视频流要求；显式合成画面承载音频属于派生媒体，不自动提供词界。

### 显式局部字幕配方准备

caption-presentation 的variant可使用 `caption_overrides` 与唯一能力 `caption-cue-style`。必须由调用者在 `scope.caption_ids` 指定目标、`caption_style=false`；未选字幕不自动加入范围。沿用2–4个明确variant、冻结全部clip位置/总时长、无其它内容编辑的限制。只准备既有style-recipe-preview，不直接应用Work。

若已有全局编译绑定，完整旧映射与约束必须原值携带；新cue配方只改变选择的cue覆盖。准备器先核绑定/目标/字段，真正全有效字幕布局与CAS仍由下游compiler/preview复核，准备成功不表示渲染、布局或风格效果通过。
