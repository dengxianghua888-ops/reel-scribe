# 可执行呈现配方（style-recipe/1）

`style-recipe-compile` 把**明确参数**编译为现有 `work-candidate/1`，不创建第二套作品状态。它不是完整叙事风格执行器，不会自动选段、改写内容、修剪停顿、添加音乐或推荐“最佳”风格。

## 输入

- `operation`: `style-recipe-compile`
- `document`、`expected_document_sha256`、`base_version`：当前 Work 文档及其绑定身份。
- `recipe`、`expected_recipe_sha256`：下面的配方和完整配方 `fingerprint`。配方 ID 和 version 由作者声明，摘要绑定实际字段；修改任一字段须重新生成摘要。
- `capabilities`：调用者明确声明的目标能力，允许 `caption-style`、`audio-track-gain`、`caption-cue-style`，不得重复。不是运行时探测或真实宿主能力证明。
- `scope`：与 `timeline-revise` 完全相同的明确授权范围。全局默认字幕变化需要 `caption_style: true`，局部覆盖需对应 `caption_ids`（见下节）；每个修改音轨 ID 需在 `audio_ids`；全局风格绑定 `*` 需在 `style_keys`。不要为方便放开其他范围。

配方结构：

```json
{
  "schema": "style-recipe/1",
  "id": "faithful-clean-caption-neutral",
  "version": "0.1.0",
  "style": {
    "family": "原貌与亲近",
    "style_id": "faithful-clean",
    "version": "0.1.0",
    "card": {"path": "/absolute/checkout/styles/speech/faithful-clean.md", "sha256": "实际卡片 SHA-256"}
  },
  "parameters": {"caption_style": {"font_size": 42, "margin_v": 72, "color_rgb": "FFFFFF"}}
}
```

`parameters.caption_style` 仅允许 `font_size`、`margin_v`、`color_rgb`；复用现有字体及其哈希，必须已有合法字幕样式。字号为 8–300 整数；下边距为非负整数且小于画布高度；颜色为六位 RGB 十六进制。尺寸仍需真人阅读与遮挡检查，示例不是通用最佳值。

`parameters.audio_gain_db` 为 `{已有音轨ID: 增益dB}`，范围 -120 到 24。只能改指定音轨的固定增益，不等于自动 ducking、角色辨别或完整听检。原片 clip 的 gain、源窗、速度、顺序、字幕文字/时间、证据映射、备注和视觉层不修改。

未知参数、空配方、能力缺失、卡片哈希不符、版本过期或范围不足均拒绝，无自动降级。卡片身份绑定不证明选用卡片适合素材；全局 `*` 绑定明确替换，需要调用者事先同意这一范围。卡片中叙事/节奏意图未在本操作中执行。

## 输出与采用

- `candidate.json`：现有 Work 候选，随后用 `work-render` 预览、人工审阅，并经 `work-version commit` 的权威状态/CAS 再检才可采用。仅编译不改当前 Work 或原素材。
- `revision-diff.json`：沿用 Work 的范围检查与保守失效列表。
- `style-recipe.json`：记录实际映射参数和候选摘要；状态 `CANDIDATE_COMPILED`，`render: NOT_RUN`、`style_effect: NOT_VERIFIED`、`applied_to_work: false`。这是参数编译证据，不是参数已在成片生效证据。

示例位于 `examples/style-recipes/`，均 authored-unvalidated，只演示呈现层。没有真实媒体效果、盲评或编辑器往返验收。换配方产生新候选并重新验证，不能继承旧成片验收。实际渲染、语义正确性、可读性、响度和风格适切性必须在目标作品上检查。

## 可选真实字幕覆盖检查

配方可增加 `layout_constraints`，它和配方一起绑定摘要，并写入候选的风格绑定：

```json
{"schema":"caption-layout/1","canvas":{"width":960,"height":636},
 "subtitle_band":{"x":0,"y":592,"width":960,"height":44},
 "protected_regions":[{"id":"caller-declared-screen-content",
 "rect":{"x":0,"y":48,"width":960,"height":540}}]}
```

所有矩形为**成片画布像素**、整数、正面积、半开范围；调用者必须明确画布与保护区，不是系统识别 UI。示例描述一个已存在空白字幕带的画布，不会创建黑边或改变源画面。声明带与保护区相交即拒绝。无约束的旧调用保持兼容并返回 `caption_layout.status=UNKNOWN`。

有约束时，编译真实调用 FFmpeg/libass，用与 `caption-burn` 共享的 ASS 生成器、相同字体文件/样式，在透明画布上逐 cue 生成字形及描边 alpha mask，不根据视频颜色猜文字。覆盖检查仅支持不重叠、无动态 ASS 控制语法、无显式换行/制表或连续空白的静态字幕（允许renderer自然换行；特殊排版明确拒绝，而普通caption-burn不改变），每条 cue 的字形在显示期不变。原尺寸 mask 必须与扩大画布、同步平移边距后的中心区域逐像素一致；扩大画布中越出原画布的字形视为截断。对实际包围盒额外扩 2 像素，必须落在声明带内且不与保护区相交，不能仅凭声明带背书。

成功为 `STATIC_GLYPH_COVERAGE_VERIFIED`，只证明当前字体配置、脚本和工具下的**编码前静态字幕 alpha 覆盖**；不证明字形没有 fallback、文字正确、整体美观可读、UI 标注完整或编码后的所有边缘像素。改变字体、参数、内容、画布、工具或保护区必须重验。编译仍不改 Work、不渲染正式成片、不自动采用。

证据在 `layout/layout-report.json`，绑定候选文档/约束/字体/renderer、每 cue 时间与文字摘要、原尺寸和扩展 alpha PNG、ASS 及实际范围。缺工具或无法证明等价时拒绝该约束调用，不伪造通过。正常无约束编译不会增加 mask 工作量。

资源上限：画布每边≤1920、cue≤256、每cue文字≤256码点、整次扩大mask总像素≤2亿；超限明确拒绝，不能静默抽样。字体仅拷贝一次，逐cue处理，raw临时帧转换成可复核的无损alpha PNG后移除，避免长期积累巨型raw文件。显示性能、专名/否定语义、声文对齐仍需独立验收。

## 显式单条字幕呈现覆盖

`parameters.caption_overrides` 为非空 `{caption_id: {font_size,color_rgb,margin_v}}`，每条也非空，能力为 `caption-cue-style`。只允许已有cue，不改文字、时间、clip、字体或font_family。字段须满足底层 `style_override` 的整数、色值与画布边界规则；不推断哪个字幕应被选中。

此入口严格局部：`scope.caption_ids` 必须显式列本次目标，且均在参数映射中；`scope.caption_style=false`，`style_keys=['*']` 仍需授权。不支持同时改变全局默认或音轨增益。已有全局/音轨映射可原值携带以保全绑定，但不能借此修改；不得扩大scope来偷偷编辑未选字幕。

有既有编译绑定时，仅支持唯一`*`、同style/card与未失真的映射。新配方必须保留旧全局/音轨参数、非目标cue映射及原layout_constraints；目标cue也不能删除既有覆盖字段。丢字段、约束变化、已有值与绑定不符或不兼容绑定均拒绝。当前绑定已有cue映射时，全局-only配方也不能把它静默替换掉。

`*`表示这一份完整配方声明的记录位置，不表示所有cue都用了同一有效样式：`caption_style`只记录默认，`caption_overrides`逐ID记录覆盖；报告`caption_target_ids`为本次目标。未选cue和其它内容保持，新的配方ID/摘要记录这一完整映射，不认证整套风格有效。

有layout_constraints时，使用所有cue合并默认与覆盖后的完整候选检查，不只检查目标cue。任一安全带/保护区检查失败，不发布candidate。无约束时仍明确UNKNOWN，不宣称可读或不遮挡。实际字体、画面、听看与最终采用仍需独立验证。旧无override、无现存cue绑定的配方调用保持兼容。

## 已绑定作品的独立音轨首尾淡变

`parameters.audio_envelope` 为非空 `{已有音轨ID: envelope}`，能力 `audio-track-envelope`。包络沿用 Work 的48kHz样本级 `tri/qsin` 结构、端点对齐和持久保护拒绝；仅编译候选，不自动采用、不认证听感。已有绑定限定唯一可重建摘要并逐项符合当前值的 `*` 编译配方。必须保留旧参数与 layout_constraints，不支持未知、多重或失真绑定；未选映射不得改变。显式 cue 修改可原值携带包络但不得顺带改变。

局部撤销须显式 binding_resolution，派生新配方并保留其它映射和布局。原先缺省包络时恢复缺省并移除对应配方映射，不用 null 冒充无包络；若派生配方完全为空仍拒绝。后改非映射 gain/notes 保留；同字段冲突、源/锚点变化及 scope 不足拒绝。仅删除实际包络但保留原映射也拒绝，不留下失真风格声明。
