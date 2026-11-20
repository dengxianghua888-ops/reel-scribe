# 作品调色合同（work-color/1）

WorkDocument 的可选 `color` 段记录**调用方已经决定**的调色：每个素材的色彩解释、若干调色层、它们作用于哪些片段，以及应用顺序。代码不选风格、不判断好看；调色层的参数从哪里来，属于上层决策和证据。

## 结构

```text
color: {
  schema: work-color/1,
  inputs: {source_id: {space: bt709-sdr | srgb-sdr, range: limited | full,
                       basis: verified-metadata | caller-declared}},
  grades: {grade_id: {targets: "*" 或 [clip_id, ...],
                      interpretation: bt709-sdr-display | srgb-sdr-display,
                      ops: [...], strength: 0..1（可选）, lut_size: 17 | 33 | 65}},
  order: [grade_id, ...]
}
```

- `inputs`：
  - 键必须是计划中的素材 ID。
  - 按素材实际的色彩标签校验：`verified-metadata` 要求标签齐全且一致；`caller-declared` 允许缺失，但仍拒绝冲突标签。
  - HLG、PQ 素材拒绝。
- `grades`：
  - `ops`、`strength` 的字段与范围与 [color-grade-compile](color-grade-contract.md) 相同，grade_id 即编译时的 ID（不得含引号、换行或 `#`）。
  - `targets` 为 `"*"`（全部片段）或片段 ID 列表。
  - 每个目标片段的素材都必须在 `inputs` 中声明，且声明的解释与调色层一致：`bt709-sdr` 对应 `bt709-sdr-display`，`srgb-sdr` 对应 `srgb-sdr-display`。
  - 最多 16 层。
- `order`：每个调色层恰好出现一次，按此顺序叠加。文档以规范化 JSON 存储，字典键会排序，所以顺序必须显式写出。

## 渲染

`work-render` 的步骤为：时间线 → **调色** → 混音 → 叠层 → 字幕 → QC。
- 字幕和叠层在调色之后合成，因此不会被调色。
- 每个调色层先用 `color-grade-compile` 编译成 cube，然后由一次 `color-lut-apply`（`layers` 模式）按各层目标片段的输出帧区间依次套用。层与层之间保持 32 位浮点 RGB，区间外的帧只重编码。
- `color-lut-apply` 在每个区间的中间帧，以及一帧不在任何区间内的帧上读回解码结果。读回按固定分析尺寸逐点取样、不做平均，用请求的插值方式对同一批源像素做 numpy 预测并比较（ΔE2000 中位数不超过 3，否则失败）。
- 回执记录每层的片段、帧区间和编译后的 cube 哈希。
- 时间线本身不受调色影响。目前 A/B 预览的每个变体仍各自渲染时间线，还没有复用。

时间线输出继承第一个片段素材帧上的色彩标签。调色步骤按有限范围、以调用方声明为依据（`caller-declared`）交给 `color-lut-apply`，并沿用时间线输出的实际传递函数标签：sRGB 标签按 `srgb-sdr` 套用并保持该标签，BT.709 或缺失标签按 `bt709-sdr`，其他标签以 `WORK_COLOR_TIMELINE_TRANSFER_UNSUPPORTED` 拒绝。LUT 只作用于码值，每个调色层的解释已经在作品校验阶段按素材逐一核对，标签只用于一致性检查和保持管线原有的标签。sRGB 素材的码值不做传递函数转换；调色层用 `srgb-sdr-display` 时，其中的数学按 sRGB 曲线计算。

## 修订范围

`scope` 新增两个可选键：

- `grade_ids: []`：新增、删除、修改或调整顺序的调色层都必须列在这里。
- `color_inputs: false`：`inputs` 的任何变化都需要 `true`。

调色层本身没变、但它覆盖的源内容变了，也必须把它列入 `grade_ids`，否则报 `COLOR_REVIEW_SCOPE_REQUIRED`，表示被调色的是新素材，需要复核。“源内容”指目标片段的素材、哈希、源区间和速度。例如：

- 改了被调色片段的源区间；
- 换了素材；
- 往 `targets: "*"` 的作品里加了新片段。

只移动片段位置、内容不变，不需要复核：调色跟随片段走。覆盖内容按片段 ID 比较，与时间线顺序无关，所以互换同一调色层下两个片段的顺序也不需要复核。

调色段的任何变化都会使渲染、技术 QC、内容复核和画面复核失效。差异报告新增以下字段：
- `color_grades`、`color_inputs_changed`、`color_order_changed`：调色段本身的变化；
- `color_revalidation_declared`：因源内容变化而声明复核的调色层。

## 局部撤销

`work-version` 的 `prepare-local-undo` 接受选择器 `{kind: color_grade, id: <调色层 ID>, field: ops | strength | targets | interpretation | lut_size}`，规则与其他字段相同：

- 对所选字段做“父版本（before）/ 所选修订（after）/ 当前头”三方比较：当前等于 after 时恢复 before，已等于 before 时为 `NO_OP`，第三种值视为冲突，不产生候选。
- 比较包括字段是否存在。`strength` 可选：撤销“首次加上强度”会删掉该字段，而不是写入默认值。其余字段必须三方都存在，否则 `UNDO_FIELD_MISSING`；不能借局部撤销恢复已删除的调色层，也不能改 `order`。
- 范围必须显式列出该调色层（`grade_ids`）。没选中的调色层、其他字段、之后的编辑全部保留。
- 恢复后的整份候选仍走 `revision_diff` 和作品校验，例如恢复后的 `targets` 指向的片段已被删除，会照常报错。

## 风格配方参数组

`style-recipe-compile` 新增参数组 `parameters.color_grade: {grade_id: {targets, interpretation, ops, strength?, lut_size}}`，能力名 `color-grade`：

- 只写入 `color.grades` 中列出的调色层，已有层保持原位置。新层按调色层 ID 排序后追加到 `order` 末尾：配方摘要不含 JSON 对象的键顺序，按字典顺序追加会让同一份配方产生不同的叠加顺序。需要别的顺序时，编译后再用 `timeline-revise` 调整 `order`。
- 作品必须已有 `color` 段（`EXISTING_COLOR_INPUTS_REQUIRED`）。素材的色彩解释是关于素材的事实，不属于风格选择，配方不能声明或改写 `inputs`。
- 范围仍需显式授权：调色层列入 `grade_ids`，绑定需要 `style_keys: ["*"]`。
- 逐条字幕（cue）模式下，配方可以原样携带已有调色层，但任何改动都以 `CUE_RECIPE_GLOBAL_CHANGE_FORBIDDEN` 拒绝；反过来，调色配方可以原样携带已绑定的逐条字幕覆盖，但必须完整携带：与绑定中的覆盖集合不同报 `CUE_RECIPE_BINDING_PARAMETERS_DROPPED`，排版约束不一致报 `CUE_RECIPE_CONSTRAINTS_MUST_PERSIST`，改动值报 `CUE_RECIPE_UNSELECTED_OVERRIDE_CHANGED`。
- `style-recipe-preview` 直接复用这一参数组：2–4 个调色变体各自编译为候选，经批量渲染生成预览，作品头不变。这就是调色 A/B 预览，代码不评判哪个更好。

绑定了配方的作品做调色局部撤销，仍需显式的 `binding_resolution`。规则同[作品合同](work-contract.md)：当前作品中所有已映射的调色层必须与原配方一致，否则以 `UNDO_BINDING_ALREADY_DIVERGED` 拒绝；所选字段必须已在配方中映射；派生配方只改所选字段及显式给出的新 ID/版本。

## 变更影响

`revision-impact-inspect` 的阶段列表在时间线与字幕排版之间新增 `color-grade`。

| 分类 | 触发条件 | 需重做阶段 |
|---|---|---|
| `color-grade-or-order` | 调色层增删改、`inputs` 变化、`order` 变化 | `color-grade`、`render` |
| `color-coverage` | 调色层未变，但覆盖的源内容变了，已声明复核 | `color-grade`、`render` |

时间线变化本身另有分类；它带来的重新调色由 `color-coverage` 体现。旧整份文档的 QA 失效规则不变。

## 限制

- 只支持 SDR 的 BT.709 与 sRGB 解释，Log、HDR 和广色域转换留给 C4。
- 只有在调用方声明了色彩解释，且标签不冲突时才调色；代码不会推断素材该用哪种解释。
- 传递函数混用的时间线（如 sRGB 照片与 BT.709 视频混剪）仍按声明逐片段校验和调色，但输出只带第一个片段的传递函数标签，这一标签不能代表所有片段。真实素材实测见[作品调色真实素材操作记录](../docs/color-work-real-run-20261120.md)。
- 调色层不等于风格绑定；`style_bindings` 仍只是创作记录，配方映射只说明“这些参数来自这份配方”，不证明调色效果符合风格卡的意图。
- 保护项门禁（色彩一致性检查、肤色等受保护范围）尚未接入，属于 C2c。
