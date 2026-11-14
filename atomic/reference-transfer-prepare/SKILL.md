---
name: reference-transfer-prepare
description: 将参考片的显式观察和逐项采纳、调整、放弃决定转成受限字幕呈现请求，不自动分析参考、不渲染、不提交。
---

依据[参考迁移合同](../../contracts/reference-transfer-contract.md)，记录参考源SHA、实际观察区间、观察方法及证据身份。未观察项标 unobserved 并 omit，不能凭宣传或文件存在声称已看听。

逐项选择 adopt/adapt/omit，明确理由，隔离 narrative 与 audiovisual。每次最多一个采纳机制：audiovisual/caption-presentation 生成 style-recipe-preview，或 narrative/result-first 仅 adapt 到明确教程目标。后者要求至少两个已观察的结果预览→原流程区间及逐段证据，单帧不证明叙事顺序；显式保留未知，不从参考推断目标因果。音乐及其它机制仅可放弃，不暗中迁移。观察证据身份不认证内容真实性。

准备成功不代表真实效果、完整风格或权限已通过。执行前核参考与Work版本、用户意图及必要权限，运行既有下游验证。此入口不改Work、不把参考媒体插入作品、不签发授权。

结果前置路径调用现有 result-preview-compile 在临时目录验证目标源窗、完整原流程、标签、scope与持久保护，随后丢弃临时候选。报告明确执行过临时编译，不渲染、不改Work。后续使用prepared请求仍须重核当前头并重新编译；不能解除保护或忽略独立音轨限制。

报告使用 `reference-transfer/2`，去掉旧 `reference_media_in_output` 字段。`reference_media_inserted_by_transfer=false` 仅指本操作不新增参考媒体；`reference_target_source_matches` 按SHA列当前Work主源、音轨、视觉层的同身份引用，不能当实际消费记录。`reference_output_presence=NOT_EVALUATED` 保留成片存在性未知；无同SHA也不排除转码或裁切派生素材。同源参考允许，但不算独立参考研究证据。

## 显式两维组合（可选编译模式）

用户明确需要“参考 A 结果先行 + 参考 B 文字呈现”时，另用合同的 `composition: result-first-then-caption` 请求形状；旧单参考最多一个机制的限制不放宽。仅软件目标、两个不同媒体摘要、各一个已观察 adapt 项、明确选定一个字幕变体及 final_scope。A 临时编译后，B 对新片段集合和中间文档重新绑定；最终再对原 Work 基线校验显式总范围。只支持全局字幕字号/颜色/边距，不迁入参考正文、字幕时轴、音频或额外来源。

此模式实际编译最终普通候选而不是仅准备请求；输出 `reference-composition/1` 和可复核中间文档，原头不改，渲染与采用另行执行。存在布局约束时需真实 FFmpeg/libass 和字体，不把通常准备路径的 sqlite/ffprobe 检查当作完整依赖满足。临时 Work 不作为交付或执行依赖。原目标源会被前置预览重复，可能与参考同源；报告仅说明没有导入外部参考来源，不能断言参考内容不存在于成片。
