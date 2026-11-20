# 调色一致性与保护项检查（color-consistency/1）

`color-consistency-check` 比较**同一时间线调色前后**的两条视频，测量调色改变了什么。它不调色、不选风格、不检测人脸或肤色，也不给审美分数。

## 请求

| 字段 | 约束 |
|---|---|
| `reference` / `candidate` | `{path, sha256}`，调色前与调色后；结束时复核字节未变。两者帧数、宽高必须一致，否则 `COLOR_CHECK_VIDEOS_NOT_ALIGNED` |
| `input_color` | `{space: bt709-sdr 或 srgb-sdr, range, basis}`，两条视频都按[色彩特征合同](color-profile-contract.md)的规则校验标签 |
| `segments` | 1–256 段 `{id, start_frame, end_frame, space?}`，输出帧号 `[start, end)`，按顺序且不重叠。`space` 可覆盖该段换算 CIELAB 时用的解释，例如 sRGB 照片与 BT.709 视频混剪 |
| `samples_per_segment` | 1–8；每段均匀取样，另取每个样本的下一帧（仍在段内时）测闪烁。解码总帧数超过 512 拒绝（`COLOR_CHECK_FRAME_LIMIT`） |
| `protections`（可选） | 至多 16 项，见下 |
| `limits`（可选） | `max_flicker_increase`、`max_clip_increase`、`max_drift_increase`、`max_out_of_range_fraction`，任选，非负数 |

### 保护项

```text
{kind: hue-range, segments: [段 ID...], hue_degrees: [h0, h1], min_chroma: C, box?: [x0, y0, x1, y1],
 max_median_delta_e2000: T, action: fail | flag}
{kind: region, segments: [段 ID...], box: [x0, y0, x1, y1],
 max_median_delta_e2000: T, action: fail | flag}
```

- `hue-range`：在**调色前**的像素中选 CIELAB 色相角 h_ab 落在 `[h0, h1]`（`h0 > h1` 表示跨 0°）且色度 C*ab ≥ `min_chroma` 的像素。可选 `box` 把选择限制在调用者声明的矩形里：只按色相选会把同色物体一起算进去（真实素材中，按色相选出的宇航员“肤色”像素有九成以上落在脸部框外，主要是橙色宇航服），框住脸部才是在保护皮肤。
- `region`：0–1 归一化矩形，含义由调用者声明（品牌标志、证据色块等）。
- 对选中像素逐一计算调色前后的 CIEDE2000，汇总各段的样本帧，中位数超过 `T` 为 `VIOLATED`。
- 选中像素少于 64 个为 `UNMEASURED`。无法测量不算通过：`action: fail` 时同样使门禁失败。

## 测量

样本帧按固定分析宽度（最宽 256）**逐点取样**解码，不做平均，与 `color-lut-apply` 的读回一致。逐段报告调色前后的：

- 高光剪切（任一通道 ≥ 254）与暗部压死（三通道都 ≤ 1）比例，以及增量；
- 闪烁：样本帧与下一帧平均 L* 之差的最大值；增量逐对计算（同一对帧调色后的差减去调色前的差），取最大值，避免某一对原本就有的大幅变化掩盖调色在另一对引入的闪烁；
- 有限范围素材调色后 Y 超出 16–235 的比例（直接读 Y 码值，不做范围转换）；
- 平均 CIELAB。

相邻段之间报告平均 CIELAB 的 CIEDE2000（调色前、调色后、增量），即“跨镜头漂移”。镜头本来就可以不同，漂移只有在声明了上限时才形成门禁。

## 输出 `color-consistency.json`

`gate`：

- `FAILED`：任一 `fail` 保护项被破坏或无法测量，或任一声明的上限被超过；
- `FLAGGED`：只有 `flag` 保护项被破坏或无法测量；
- `PASSED`：其余情况。没有声明保护项和上限时总是 `PASSED`，此时只是报告数值。

`failures`、`flags` 列出原因。门禁结果写在报告里，原子本身照常成功；由调用方决定如何处理。`work-render` 遇到 `FAILED` 会以 `WORK_COLOR_CHECK_FAILED` 中止。

## 不能据此声称

- 只覆盖采样帧，通过不代表未采样帧没有问题。
- 保护项只保证调色前后颜色变化不超过阈值，不判断原来的颜色是否“正确”，也不把颜色推向任何标准值。
- `hue-range` 不是肤色、人脸或物体检测：它选中的是色相和色度符合条件的像素，可能包括背景里的同色物体，也可能漏掉阴影里的皮肤。
- 数值不代表好看或适合某个平台。
