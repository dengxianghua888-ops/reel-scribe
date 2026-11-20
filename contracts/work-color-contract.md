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
- `color-lut-apply` 在每个区间的中间帧，以及一帧不在任何区间内的帧上读回解码结果，与 numpy 对源帧的预测比较（ΔE2000 中位数不超过 3，否则失败）。
- 回执记录每层的片段、帧区间和编译后的 cube 哈希。
- 时间线本身不受调色影响，可以在不同调色变体之间复用。

时间线输出继承第一个片段素材帧上的色彩标签。调色步骤按有限范围、以调用方声明为依据（`caller-declared`）交给 `color-lut-apply`，并沿用时间线输出的实际传递函数标签：sRGB 标签按 `srgb-sdr` 套用并保持该标签，BT.709 或缺失标签按 `bt709-sdr`，其他标签以 `WORK_COLOR_TIMELINE_TRANSFER_UNSUPPORTED` 拒绝。LUT 只作用于码值，每个调色层的解释已经在作品校验阶段按素材逐一核对，标签只用于一致性检查和保持管线原有的标签。sRGB 素材的码值不做传递函数转换；调色层用 `srgb-sdr-display` 时，其中的数学按 sRGB 曲线计算。

## 修订范围

`scope` 新增两个可选键：

- `grade_ids: []`：新增、删除、修改或调整顺序的调色层都必须列在这里。
- `color_inputs: false`：`inputs` 的任何变化都需要 `true`。

调色层本身没变、但它覆盖的源内容变了，也必须把它列入 `grade_ids`，否则报 `COLOR_REVIEW_SCOPE_REQUIRED`，表示被调色的是新素材，需要复核。“源内容”指目标片段的素材、哈希、源区间和速度。例如：

- 改了被调色片段的源区间；
- 换了素材；
- 往 `targets: "*"` 的作品里加了新片段。

只移动片段位置、内容不变，不需要复核：调色跟随片段走。

调色段的任何变化都会使渲染、技术 QC、内容复核和画面复核失效。差异报告新增以下字段：
- `color_grades`、`color_inputs_changed`、`color_order_changed`：调色段本身的变化；
- `color_revalidation_declared`：因源内容变化而声明复核的调色层。

## 限制

- 只支持 SDR 的 BT.709 与 sRGB 解释，Log、HDR 和广色域转换留给 C4。
- 只有在调用方声明了色彩解释，且标签不冲突时才调色；代码不会推断素材该用哪种解释。
- 传递函数混用的时间线（如 sRGB 照片与 BT.709 视频混剪）仍按声明逐片段校验和调色，但输出只带第一个片段的传递函数标签，这一标签不能代表所有片段。真实素材实测见[作品调色真实素材操作记录](../docs/color-work-real-run-20261120.md)。
- 调色层不等于风格绑定；`style_bindings` 仍只是创作记录。局部撤销、风格配方参数组和保护项门禁在后续阶段接入。
