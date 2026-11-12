# 显式结果预览编译 v1

`result-preview-compile` 是信息顺序修改辅助入口，不增加作品权威、不提交 Work、不自动生成声音。它解决重复手拼源窗重复授权、前置标签、教程结果证据和候选范围的问题。使用现有教程编译器与 timeline-revise，后续复用 work-render。

## 请求

必需字段：`operation, store, expected_version, mechanism_card, tutorial, preview, shift_clip_ids, scope`。

- mechanism_card：`{path, sha256}`，固定到当前分发库 `styles/reference/consequence-first.md`。
- tutorial：原作品的 `{steps, result_cues}`，遵循 tutorial-plan-compile 现行字段；步骤 source-time 窗口不变，result_cues 的 output-time 随前置时长移动并重新编译。
- preview：`{id, step_id, start, end, label, return_label, return_label_seconds}`。start/end 是目标步骤 result 内的源秒，必须在作品帧网格上；首版只支持全部旧片段 1×。不得换源或自动决定结果。
- label 固定“后段画面预览 · 非当前操作已成功”；return_label 以“回到原流程”开头，最长100字。返回标签最长10秒且须在总流程内，不能与现有字幕交叠。原作必须已有有效字幕样式，不默认选择字体。
- shift_clip_ids：全部原 clip IDs，唯一且完整，明确所有旧片段输出时间后移；不等于改原 clips 内容的授权。
- scope：既有 Work scope，需开放新增 preview clip、新增 `{id}-label` / `{id}-return-label` 字幕、`result_preview` note、`allow_source_reuse` output field。原位置/时长冻结仍拒绝；不能由 helper 自动解除。

## 保持与拒绝

原 clips 内容及相对顺序、原字幕、手动 notes、来源、字幕样式不改。新增片段继承结果 carrier 的原声增益，前置同源窗，显式 `allow_source_reuse=true`。现有 `notes.result_preview` 不覆盖，直接拒绝。

非空独立 audio_tracks、非空 visual_layers 仍拒绝。已有合法持久 evidence_protection 仅在 `scope.evidence_mapping:true` 时支持受限整体后移：原 units/requires/required_units/occurrences/carriers/dependencies/chapters 声明逐字段不改，预览不加入任何 occurrence。没有此明确许可仍拒绝，不指导关闭保护绕过。 原字幕按原 clip 锚点一起后移，跨度保持；有标签冲突就拒绝，不能删用户字幕。旧教程 proof/其他外部证据不自动获得新版本效力；结果 note 记录本次重新编译的 proof，消费者须按其 plan_revision 判断适用范围。

固定卡和步骤证据均校验 SHA，编译结束再次验证并复核当前 Work 头。生成标准 candidate.json、revision-diff.json、两次教程 proof-map 及 result-preview.json；失败可能留下诊断或候选文件，但无成功 result-preview.json。不能据孤立候选文件存在判定通过或直接提交；Work 自身仍执行 CAS/范围验证。

## 验证边界

basis 固定 `authored-mechanism-only`。无独立参考视频观察，不得声称真实参考迁移完成。编译器只验证调用方声明的来源、范围、映射、依赖顺序，不解释证据图片，不证明动作造成结果。前置标签不注册为当前步骤成功的 result_cue。

本操作不渲染，render=NOT_RUN；后续真实预览须检查标签可见、回到原流程、全部原源窗保持、声画完整。音频数值一致或相关不能代替听审、原意、教学效果或用户偏好验收。

可复验测试：tests/runtime/test_result_preview.py 的合成契约不冒充真实素材；另有独立公开 wikEd 24–64 秒评估，具体素材许可/归一化/候选与视听缺口由该评估目录记录，不将单例推广到全卡。


## 持久保护共存：仅原流程整体后移

原 clips、来源、速度和相对顺序保持；新增前置预览必须在帧网格内。所有旧片段的输出起止帧均验证为增加同一个预览帧数。保护声明使用源时窗及carrier身份，不直接存输出秒；故不改声明中的章节或依赖，仅重新编译派生后的输出区间。

调用既有 `ordinary_protection` 验证前后映射，逐 occurrence/part 核原carrier、源有理时间、速度不变，输出有理起止均增加精确预览时长。输出 `base-protection-map.json` 和 `candidate-protection-map.json` 绑定各自文档摘要；该映射是普通声明范围保护，不授予strict SOURCE COMPLETE、语义或可听性通过。原报告不能移植为新版本证明。最终再核所有保护单元的源与证据文件及当前Work头。

`protection_shift.status=DECLARED_SOURCE_RANGES_PRESERVED_WITH_EXPLICIT_SHIFT` 仅在上述条件成立后返回；无保护时为NOT_PRESENT。新增preview既不是原动作也不是原结果的替代证据。删原流程、改声明、把原carrier指到preview、改变源时钟或没有映射授权均不支持。持久保护外的独立音轨/叠层仍未实现，不扩展放行。
